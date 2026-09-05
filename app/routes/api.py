"""
OpenAI兼容API路由
实现 /v1/chat/completions 和 /v1/models

M1 重构后：api.py 仅作为入口，构建 PipelineContext 后交给 Executor 统一执行。
流式/非流式的账号选择、失败切换、记账日志全部下沉到 pipeline/executor.py。

M3 企业化：支持 API Key 绑定领域权限 + 斜杠命令强制指定领域。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional
import time
import logging
import asyncio
import uuid
import hashlib
import re

from app.models import get_db, AsyncSessionLocal
from app.models.database import ModelAccount, ApiKey
from sqlalchemy import select
from app.services.balance import fetch_balance, BalanceUnsupportedError, get_today_str
from app.pipeline.context import PipelineContext
from app.pipeline.executor import Executor
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 斜杠命令正则：/code /creative /data /general，后面跟空格或结束
SLASH_COMMAND_PATTERN = re.compile(r'^/(general|code|creative|data)(?:\s+|$)', re.IGNORECASE)


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None


async def verify_bearer_token(request: Request, db: AsyncSession = Depends(get_db)):
    """
    验证 Bearer Token，返回匹配的 ApiKey 对象。

    优先级：
    1. api_key 表中匹配的 Key（企业化部署，绑定领域权限）
    2. 全局默认 token（settings.GATEWAY_BEARER_TOKEN），兼容旧版，返回 None 表示无领域限制
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少Authorization头")

    token = auth[7:]

    # 1. 先查 api_key 表
    result = await db.execute(
        select(ApiKey).where(ApiKey.api_key == token, ApiKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()
    if api_key:
        return api_key

    # 2. 兼容全局默认 token（无领域限制，全部领域可用，自动路由）
    if token == settings.GATEWAY_BEARER_TOKEN:
        return None

    raise HTTPException(status_code=401, detail="无效的Token")


def _parse_slash_command(messages: List[dict]) -> tuple[Optional[str], List[dict]]:
    """
    从最新一条 user 消息中解析斜杠命令。

    返回：(forced_domain, cleaned_messages)
    - forced_domain: 斜杠命令指定的领域，如 "code"；无命令则为 None
    - cleaned_messages: 移除斜杠前缀后的消息列表
    """
    if not messages:
        return None, messages

    # 找到最后一条 user 消息
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            content = messages[i].get("content", "")
            match = SLASH_COMMAND_PATTERN.match(content)
            if match:
                domain = match.group(1).lower()
                # 移除斜杠前缀，保留后面的内容
                cleaned_content = content[match.end():].strip()
                cleaned_messages = list(messages)
                cleaned_messages[i] = {**messages[i], "content": cleaned_content}
                logger.info(f"斜杠命令: /{domain} → 强制指定领域")
                return domain, cleaned_messages
            break  # 只检查最新一条 user 消息

    return None, messages


async def _sync_daily_balances():
    """
    每日首次请求时，异步同步各启用账号的厂商真实余额，并重置当日用量。
    """
    today = get_today_str()
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelAccount).where(ModelAccount.is_enable == True)
            )
            accounts = result.scalars().all()
            changed = False
            for account in accounts:
                if account.balance_sync_date == today:
                    continue
                account.daily_used_tokens = 0
                account.daily_used_currency = 0
                changed = True
                try:
                    unit, bal = await fetch_balance(account)
                    account.balance_remaining = bal
                    account.balance_unit = unit
                    account.balance_sync_date = today
                    logger.info(f'自动同步余额: 账号{account.id} {account.vendor} → {unit} {bal}')
                except BalanceUnsupportedError as e:
                    account.balance_sync_date = today
                    logger.info(f'账号{account.id} {account.vendor} 不支持自动获取余额: {e}')
                except Exception as e:
                    logger.warning(f'账号{account.id} {account.vendor} 余额同步失败: {e}')
            if changed:
                await session.commit()
    except Exception as e:
        logger.warning(f'每日余额同步任务异常: {e}')


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[ApiKey] = Depends(verify_bearer_token)
):
    """聊天补全接口（支持流式和非流式，失败时自动切换账号）"""

    # 每日首次请求时后台异步同步一次厂商余额
    asyncio.create_task(_sync_daily_balances())

    # 构建消息
    messages = [{"role": msg.role, "content": msg.content} for msg in req.messages]

    # 解析斜杠命令（/code /creative 等），移除前缀
    forced_domain, messages = _parse_slash_command(messages)

    # API Key 领域权限
    allowed_domains = None
    default_domain = None
    api_key_id = None
    if api_key:
        api_key_id = api_key.id
        allowed_domains = api_key.allowed_domains  # None=全部领域
        default_domain = api_key.default_domain    # None=自动路由
        logger.info(f"API Key: id={api_key.id} name={api_key.name} "
                    f"allowed={allowed_domains} default={default_domain}")

    # 斜杠命令领域权限校验：只能切换到 allowed_domains 内的领域
    if forced_domain and allowed_domains is not None:
        if forced_domain not in allowed_domains:
            logger.warning(f"斜杠命令 /{forced_domain} 不在 API Key 允许的领域 {allowed_domains} 内，忽略")
            forced_domain = None

    # 预估Token数
    estimated_tokens = sum(len(msg.get("content", "")) for msg in messages) * 0.5
    estimated_tokens = max(int(estimated_tokens), 100)

    # 额外参数
    kwargs = {}
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.max_tokens is not None:
        kwargs["max_tokens"] = req.max_tokens
    if req.top_p is not None:
        kwargs["top_p"] = req.top_p

    # 构建会话ID
    x_session = request.headers.get("X-Session-Id", "").strip()
    if x_session:
        session_id = x_session
    else:
        first_user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
        msg_hash = hashlib.md5(first_user_msg.encode("utf-8")).hexdigest()[:8]
        session_id = f"{request.client.host}:{msg_hash}"

    # 构建管线上下文
    ctx = PipelineContext(
        request_id=str(uuid.uuid4()),
        client_ip=request.client.host,
        stream=bool(req.stream),
        original_messages=messages,
        requested_model=req.model,
        kwargs=kwargs,
        estimated_tokens=estimated_tokens,
        session_id=session_id,
        api_key_id=api_key_id,
        allowed_domains=allowed_domains,
        default_domain=default_domain,
        forced_domain=forced_domain,
    )

    executor = Executor(db)
    result = await executor.execute(ctx)

    if req.stream:
        return StreamingResponse(result, media_type="text/event-stream")
    return result


@router.get("/v1/models")
async def list_models(
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_bearer_token)
):
    """列出所有可用模型"""
    from sqlalchemy import select, distinct

    result = await db.execute(
        select(distinct(ModelAccount.model_name))
        .where(ModelAccount.is_enable == True)
    )

    models = result.scalars().all()

    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "woolgate"
            }
            for model in models
        ]
    }
