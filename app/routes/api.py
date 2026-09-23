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
from typing import List, Optional, Union
import time
import logging
import asyncio
import uuid
import hashlib
import re

from app.models import get_db, AsyncSessionLocal
from app.models.database import ModelAccount, ApiKey, RequestLog
from sqlalchemy import select
from app.services.balance import fetch_balance, BalanceUnsupportedError, get_today_str
from app.pipeline.context import PipelineContext
from app.pipeline.executor import Executor
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# A3: 同一会话短时间内的下一次请求，将上一条成功日志标记为 followup（回答被接受/继续追问）
FOLLOWUP_WINDOW_SECONDS = 300


class Message(BaseModel):
    role: str
    # OpenAI 兼容 content parts 数组（如 [{"type":"text","text":"..."}]）与纯字符串均接受
    content: Union[str, List[dict], None] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None


def _normalize_content(content: Union[str, List[dict], None]) -> str:
    """
    将 OpenAI 兼容 content parts 数组规范化为纯字符串。
    客户端（OpenClaw/Dify 等）可能发送 content 数组（新版 OpenAI 格式），
    而上游厂商（如 Moonshot/kimi）要求 content 为字符串。
    数组 → 拼接所有 text 块；多模态块（图片/音频）暂以占位标注，不丢弃。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                elif item.get("text"):
                    parts.append(str(item["text"]))
                elif item.get("type") in ("image_url", "input_audio"):
                    parts.append(f"[{item['type']}]")
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


class FeedbackRequest(BaseModel):
    """A3 显式反馈上报：对某次请求（request_id）给出 up/down/neutral"""
    request_id: str
    feedback: str


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


# 每日余额同步防重入标志（并发请求时避免重复同步同一批账号）
_syncing_balances = False


async def _sync_daily_balances():
    """
    每日首次请求时，异步同步各启用账号的厂商真实余额，并重置当日用量。
    """
    global _syncing_balances
    if _syncing_balances:
        return
    _syncing_balances = True
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
    finally:
        _syncing_balances = False


async def _mark_followup_signal(session_id: str, _session=None):
    """
    A3 隐式信号——继续追问（followup）。

    同一会话在 FOLLOWUP_WINDOW_SECONDS 内发起下一次请求，
    说明上一条成功回答被用户接受并继续对话 → 给上一条成功日志打 followup 信号。
    后台执行，不影响主请求链路。

    Args:
        session_id: 会话ID
        _session: 测试注入用；为 None 时使用全局 AsyncSessionLocal
    """
    if not session_id:
        return
    try:
        from datetime import datetime
        from sqlalchemy import desc

        async def _mark(s):
            result = await s.execute(
                select(RequestLog)
                .where(
                    RequestLog.session_id == session_id,
                    RequestLog.status == "success",
                )
                .order_by(desc(RequestLog.created_at))
                .limit(1)
            )
            prev_log = result.scalar_one_or_none()
            if not prev_log or prev_log.implicit_signal:
                return
            now = datetime.utcnow()
            if prev_log.created_at and (now - prev_log.created_at).total_seconds() <= FOLLOWUP_WINDOW_SECONDS:
                prev_log.implicit_signal = "followup"
                await s.commit()
                logger.info(f"[A3] 会话 {session_id} 继续追问 → 日志 {prev_log.id} 标记 followup")

        if _session is not None:
            await _mark(_session)
        else:
            async with AsyncSessionLocal() as s:
                await _mark(s)
    except Exception as e:
        logger.warning(f"[A3] followup 信号标记失败: {e}")


@router.post("/v1/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_bearer_token),
):
    """
    A3 显式反馈上报端点。

    客户端在收到响应后，携带 request_id（响应上下文/自定义头返回）调用本接口，
    对本次请求质量给出 up / down / neutral 评价。幂等：重复提交覆盖。
    """
    if req.feedback not in ("up", "down", "neutral"):
        raise HTTPException(status_code=400, detail="feedback 必须是 up / down / neutral")

    result = await db.execute(
        select(RequestLog).where(RequestLog.request_id == req.request_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="请求日志不存在（request_id 无效）")

    from datetime import datetime
    log.user_feedback = req.feedback
    log.feedback_at = datetime.utcnow()
    await db.commit()
    logger.info(f"[A3] 反馈上报: request_id={req.request_id} feedback={req.feedback}")
    return {"ok": True, "request_id": req.request_id, "feedback": req.feedback}


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

    # 构建消息（content parts 数组 → 字符串，兼容要求字符串的上游厂商）
    messages = [{"role": msg.role, "content": _normalize_content(msg.content)} for msg in req.messages]

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
    from app.utils.token_estimator import estimate_messages_tokens
    estimated_tokens = max(estimate_messages_tokens(messages), 100)

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

    # v0.6.0 用户模型覆盖：X-Model-Preference 请求头（优先于 API Key 默认模型，低于斜杠命令）
    user_override_model = request.headers.get("X-Model-Preference", "").strip() or None
    if user_override_model:
        logger.info(f"请求头 X-Model-Preference 覆盖: {user_override_model}")

    # A7 客户端适配器分发（v0.6.0 预留：默认 OpenAI 兼容直走现有逻辑，非 OpenAI 客户端后续注册）
    from app.extensions.adapters import get_adapter
    adapter = get_adapter(request)
    if adapter.name != "openai-compat":
        # 非 OpenAI 兼容协议（预留扩展点）：由适配器解析为管线上下文
        ctx = await adapter.parse(request, db=db)
        if ctx is None:
            raise HTTPException(status_code=501, detail=f"适配器 {adapter.name} 未实现 parse()")
    else:
        # A3: 后台标记上一条成功日志为 followup（同一会话短时间继续追问 = 上一条回答被接受）
        asyncio.create_task(_mark_followup_signal(session_id))

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
            user_override_model=user_override_model,
        )

    executor = Executor(db)
    result = await executor.execute(ctx)

    if req.stream:
        # A3: 流式响应头携带 request_id，客户端据此调用 POST /v1/feedback 上报质量反馈
        return StreamingResponse(
            result,
            media_type="text/event-stream",
            headers={"X-Request-Id": ctx.request_id},
        )
    # A3: 非流式同样在响应头暴露 request_id（不侵入 OpenAI 兼容响应体）
    result.headers["X-Request-Id"] = ctx.request_id
    return result


@router.get("/v1/models")
async def list_models(
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_bearer_token)
):
    """列出对外可用模型：只暴露网关入口名（对外模型名），隐藏后端真实模型"""
    from sqlalchemy import select
    from app.models.database import SystemConfig

    result = await db.execute(
        select(SystemConfig).where(SystemConfig.id == 1)
    )
    config = result.scalar_one_or_none()
    entry_name = (config.virtual_model_name if config and config.virtual_model_name else "woolgate")

    return {
        "object": "list",
        "data": [
            {
                "id": entry_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "woolgate"
            }
        ]
    }
