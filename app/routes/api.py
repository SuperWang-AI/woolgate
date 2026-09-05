"""
OpenAI兼容API路由
实现 /v1/chat/completions 和 /v1/models

M1 重构后：api.py 仅作为入口，构建 PipelineContext 后交给 Executor 统一执行。
流式/非流式的账号选择、失败切换、记账日志全部下沉到 pipeline/executor.py。
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

from app.models import get_db, AsyncSessionLocal
from app.models.database import ModelAccount
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


async def verify_bearer_token(request: Request):
    """验证Bearer Token"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少Authorization头")

    token = auth[7:]
    if token != settings.GATEWAY_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="无效的Token")


async def _sync_daily_balances():
    """
    每日首次请求时，异步同步各启用账号的厂商真实余额，并重置当日用量。

    - 仅当账号 balance_sync_date != 今天 时才执行（每天最多一次）
    - 跨天时先清零当日用量(daily_used_*)，再同步新余额 → 预计余额 = 新初始额度 - 当日用量
    - 独立 session，不写请求日志、不扣费 → 不影响正常请求
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
                # 新的一天：重置当日本地用量
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
                    # 不支持自动获取的厂商，标记今日已尝试，避免每次请求都重复探测
                    account.balance_sync_date = today
                    logger.info(f'账号{account.id} {account.vendor} 不支持自动获取余额: {e}')
                except Exception as e:
                    # 同步失败不阻塞本次请求，也不标记今日（次日再试）
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
    _auth: None = Depends(verify_bearer_token)
):
    """聊天补全接口（支持流式和非流式，失败时自动切换账号）"""

    # 每日首次请求时后台异步同步一次厂商余额（不阻塞、不影响正常计数）
    asyncio.create_task(_sync_daily_balances())

    # 预估Token数（简单估算：每个字符约0.5 token）
    estimated_tokens = sum(len(msg.content) for msg in req.messages) * 0.5
    estimated_tokens = max(int(estimated_tokens), 100)

    # 构建消息
    messages = [{"role": msg.role, "content": msg.content} for msg in req.messages]

    # 额外参数
    kwargs = {}
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.max_tokens is not None:
        kwargs["max_tokens"] = req.max_tokens
    if req.top_p is not None:
        kwargs["top_p"] = req.top_p

    # 构建管线上下文，统一交给 Executor 执行
    session_id = request.headers.get("X-Session-Id", "").strip() or request.client.host
    ctx = PipelineContext(
        request_id=str(uuid.uuid4()),
        client_ip=request.client.host,
        stream=bool(req.stream),
        original_messages=messages,
        requested_model=req.model,
        kwargs=kwargs,
        estimated_tokens=estimated_tokens,
        session_id=session_id,
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
