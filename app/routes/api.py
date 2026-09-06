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
    1. api_key 表中匹配的 Key（可配置默认领域）
    2. 全局默认 token（settings.GATEWAY_BEARER_TOKEN），兼容旧版，返回 None
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

    # 2. 兼容全局默认 token
    if token == settings.GATEWAY_BEARER_TOKEN:
        return None

    raise HTTPException(status_code=401, detail="无效的Token")


async def _parse_slash_command(
    messages: List[dict], valid_models: List[str]
) -> tuple[Optional[str], List[dict]]:
    """
    从最新一条 user 消息中解析斜杠命令（指定模型）。

    Args:
        messages: 消息列表
        valid_models: 有效模型列表（从 model_catalog 动态读取）

    返回：(forced_model, cleaned_messages)
    - forced_model: 斜杠命令指定的模型；无命令或命令无效则为 None
    - cleaned_messages: 移除斜杠前缀后的消息列表
    """
    if not messages or not valid_models:
        return None, messages

    # 构建动态正则：/(model1|model2|...)，后面跟空格或结束
    model_pattern = "|".join(re.escape(m) for m in valid_models)
    pattern = re.compile(rf'^/({model_pattern})(?:\s+|$)', re.IGNORECASE)

    # 找到最后一条 user 消息
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            content = messages[i].get("content", "")
            match = pattern.match(content)
            if match:
                model = match.group(1)
                # 移除斜杠前缀，保留后面的内容
                cleaned_content = content[match.end():].strip()
                cleaned_messages = list(messages)
                cleaned_messages[i] = {**messages[i], "content": cleaned_content}
                logger.info(f"斜杠命令: /{model} → 强制指定模型")
                return model, cleaned_messages
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

    # 动态读取有效模型列表（用于斜杠命令解析）
    from app.models.database import ModelCatalog
    result = await db.execute(
        select(ModelCatalog).where(ModelCatalog.is_active == True)  # noqa: E712
    )
    valid_models = [m.model_name for m in result.scalars().all()]

    # 解析斜杠命令（/qwen-plus /kimi-k2.6 等），有效模型列表动态校验
    forced_model, messages = await _parse_slash_command(messages, valid_models)

    # API Key 默认模型（可选，为空则向量/LLM 路由自动选择）
    default_model = None
    api_key_id = None
    if api_key:
        api_key_id = api_key.id
        default_model = api_key.default_model
        if default_model:
            logger.info(f"API Key: id={api_key.id} name={api_key.name} default_model={default_model}")

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
        default_model=default_model,
        forced_model=forced_model,
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
