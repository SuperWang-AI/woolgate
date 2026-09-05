"""
OpenAI兼容API路由
实现 /v1/chat/completions 和 /v1/models
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import time
import logging
import asyncio
from datetime import datetime

from app.models import get_db, AsyncSessionLocal
from app.models.database import RequestLog, ModelAccount
from sqlalchemy import select
from app.services.router import AccountRouter
from app.services.llm_client import llm_client
from app.services.balance import fetch_balance, BalanceUnsupportedError, get_today_str
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
    
    # 流式：将账号重试与切换逻辑下沉到 stream_with_failover 生成器内部。
    # StreamingResponse 惰性执行，上游异常发生在响应发送阶段，
    # 外层 try/except 无法捕获，故由 stream_with_failover 自行管理账号选择与切换。
    if req.stream:
        return StreamingResponse(
            stream_with_failover(
                db, req, messages, kwargs, estimated_tokens, request.client.host
            ),
            media_type="text/event-stream"
        )

    # 非流式：由本函数循环管理重试（最多重试3次，尝试不同账号）
    max_retries = 3
    last_error = None
    tried_accounts = set()
    
    for attempt in range(max_retries):
        # 选择账号（排除已尝试失败的）
        router_service = AccountRouter(db)
        account = await router_service.select_account(
            model_name=req.model,
            estimated_tokens=estimated_tokens,
            messages=messages  # 传递消息历史
        )
        
        if not account:
            if tried_accounts:
                # 所有账号都试过了
                raise HTTPException(
                    status_code=503,
                    detail=f"所有账号均不可用。最后错误: {last_error}"
                )
            else:
                # 没有可用账号
                raise HTTPException(
                    status_code=503,
                    detail=f"没有可用账号用于模型: {req.model}"
                )
        
        # 避免重复尝试同一个账号
        if account.id in tried_accounts:
            logger.warning(f"账号 {account.id} 已尝试过，跳过")
            continue
        
        tried_accounts.add(account.id)
        logger.info(f"尝试账号 {account.id} (第 {attempt + 1} 次尝试)")
        
        try:
            return await non_stream_handler(db, account, messages, kwargs, request.client.host)

        except HTTPException:
            # HTTP异常直接抛出（如认证失败等）
            raise

        except Exception as e:
            last_error = str(e)
            logger.warning(f"账号 {account.id} 失败: {last_error}，尝试下一个账号")

            # 标记账号失败
            await router_service.mark_account_failed(account.id)
            await db.commit()

            # 如果是最后一次尝试，抛出异常
            if attempt == max_retries - 1:
                raise HTTPException(
                    status_code=503,
                    detail=f"所有账号均失败。最后错误: {last_error}"
                )

            # 继续尝试下一个账号
            continue


async def stream_with_failover(
    db: AsyncSession,
    req: ChatCompletionRequest,
    messages: list,
    kwargs: dict,
    estimated_tokens: int,
    client_ip: str
):
    """
    SSE流式处理（带账号自动切换）

    规则：
    - 账号在"未输出任何内容"前失败 → 标记失败并自动切换下一个账号重试
    - 账号已开始输出后失败 → 不能切换（客户端已收到部分内容，无法重放），返回错误事件结束
    - 任何失败均以 SSE error chunk 正常结束，绝不中断连接（避免客户端报 ChunkedEncodingError）
    """
    max_retries = 3
    last_error = None
    tried_accounts = set()

    for attempt in range(max_retries):
        # 选择账号（排除已尝试失败的）
        router_service = AccountRouter(db)
        account = await router_service.select_account(
            model_name=req.model,
            estimated_tokens=estimated_tokens,
            messages=messages  # 传递消息历史
        )

        if not account:
            if tried_accounts:
                msg = f"所有账号均不可用。最后错误: {last_error}"
            else:
                msg = f"没有可用账号用于模型: {req.model}"
            logger.warning(msg)
            yield f"data: {json.dumps({'error': {'message': msg, 'type': 'no_available_account'}}, ensure_ascii=False)}\n\n"
            return

        # 避免重复尝试同一个账号
        if account.id in tried_accounts:
            logger.warning(f"账号 {account.id} 已尝试过，跳过")
            continue

        tried_accounts.add(account.id)
        logger.info(f"尝试账号 {account.id} (第 {attempt + 1} 次尝试)")

        produced_any = False  # 是否已开始输出
        try:
            async for chunk in stream_account(db, account, messages, kwargs, client_ip):
                if not produced_any:
                    produced_any = True
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            # 账号流正常结束（已收到上游 [DONE]）
            yield "data: [DONE]\n\n"
            return

        except HTTPException:
            raise

        except Exception as e:
            last_error = str(e)
            logger.error(f"账号 {account.id} 流式请求失败: {last_error}", exc_info=True)

            if produced_any:
                # 已经开始输出，不能切换账号，直接返回错误
                logger.error(f"账号 {account.id} 已输出内容后中断，无法切换账号")
                error_chunk = {
                    "error": {
                        "message": f"请求中断: {last_error}",
                        "type": "stream_error"
                    }
                }
                yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
                return

            # 未输出内容，标记账号失败并尝试下一个账号
            logger.warning(f"账号 {account.id} 输出前失败: {last_error}，尝试下一个账号")
            await router_service.mark_account_failed(account.id)
            await db.commit()
            continue

    # 所有账号均失败（全部在输出前失败），以 SSE error chunk 正常结束
    error_chunk = {
        "error": {
            "message": f"所有账号均失败。最后错误: {last_error}",
            "type": "no_available_account"
        }
    }
    yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"


async def stream_account(
    db: AsyncSession,
    account,
    messages: list,
    kwargs: dict,
    client_ip: str
):
    """
    单个账号的流式消费

    产出上游 chunk，并负责扣费与请求日志；
    异常向上传播，由 stream_with_failover 决定切换账号或返回错误。
    """
    start_time = time.time()
    prompt_tokens = 0
    completion_tokens = 0
    error_occurred = False
    error_message = None

    try:
        async for chunk in llm_client.chat_completion_stream(account, messages, **kwargs):
            # 提取token统计
            if "usage" in chunk:
                usage = chunk["usage"]
                if usage:  # 确保 usage 不是 None
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)

            yield chunk

    except Exception as e:
        error_occurred = True
        error_message = str(e)
        logger.error(f"流式请求失败: {e}", exc_info=True)
        raise  # 向上传播，由外层决定切换账号或返回错误

    finally:
        # 记录日志和扣费
        response_time = int((time.time() - start_time) * 1000)

        router_service = AccountRouter(db)
        try:
            # 记录消耗（token 计数 + 金额统计）
            await router_service.deduct_quota(
                account.id,
                prompt_tokens,
                completion_tokens
            )

            # 写入请求日志
            log = RequestLog(
                account_id=account.id,
                vendor=account.vendor,
                model_name=account.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                status="success" if not error_occurred else "failed",
                error_message=error_message,
                response_time_ms=response_time,
                client_ip=client_ip,
                endpoint="/v1/chat/completions"
            )
            db.add(log)
            await db.commit()
        except Exception as log_err:
            logger.error(f"记录请求日志失败: {log_err}", exc_info=True)


async def non_stream_handler(
    db: AsyncSession,
    account,
    messages: list,
    kwargs: dict,
    client_ip: str
):
    """非流式处理"""
    start_time = time.time()
    error_occurred = False
    error_message = None
    
    try:
        response = await llm_client.chat_completion(account, messages, **kwargs)
        
        # 提取token统计
        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        # 记录消耗（token 计数 + 金额统计）
        router_service = AccountRouter(db)
        await router_service.deduct_quota(
            account.id,
            prompt_tokens,
            completion_tokens
        )
        
        # 记录日志
        response_time = int((time.time() - start_time) * 1000)
        log = RequestLog(
            account_id=account.id,
            vendor=account.vendor,
            model_name=account.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            status="success",
            response_time_ms=response_time,
            client_ip=client_ip,
            endpoint="/v1/chat/completions"
        )
        db.add(log)
        await db.commit()
        
        return JSONResponse(content=response)
        
    except Exception as e:
        error_occurred = True
        error_message = str(e)
        logger.error(f"非流式请求失败: {e}", exc_info=True)
        
        # 标记账号失败
        router_service = AccountRouter(db)
        await router_service.mark_account_failed(account.id)
        
        # 记录失败日志
        response_time = int((time.time() - start_time) * 1000)
        log = RequestLog(
            account_id=account.id,
            vendor=account.vendor,
            model_name=account.model_name,
            status="failed",
            error_message=error_message,
            response_time_ms=response_time,
            client_ip=client_ip,
            endpoint="/v1/chat/completions"
        )
        db.add(log)
        await db.commit()
        
        # 向上抛出原始异常，让 chat_completions 处理重试
        raise


@router.get("/v1/models")
async def list_models(
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_bearer_token)
):
    """列出所有可用模型"""
    from sqlalchemy import select, distinct
    from app.models.database import ModelAccount
    
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
