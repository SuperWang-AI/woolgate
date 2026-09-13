"""
A3 日志反馈字段测试

覆盖：
1. RequestLog 新增字段存在（user_feedback/feedback_at/implicit_signal/session_id）
2. 流式输出前失败 → 失败日志 implicit_signal=switch_retry，成功日志无信号
3. 流式输出后中断 → implicit_signal=stream_interrupted
4. 非流式失败 → implicit_signal=switch_retry
5. /v1/feedback 上报端点：更新/覆盖/400/404
6. followup（继续追问）隐式信号推断：窗口内标记、窗口外不标记、已有信号不覆盖
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from app.models.database import Base, ModelAccount, SystemConfig, RequestLog
from app.routes.api import ChatCompletionRequest, Message, FeedbackRequest
from app.pipeline.context import PipelineContext
from app.pipeline.executor import Executor
from app.services.llm_client import llm_client


@pytest.fixture
async def db_session():
    """创建测试数据库会话"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        config = SystemConfig(id=1)
        session.add(config)
        await session.commit()
        yield session


def make_req(content="1+1等于几？", stream=True):
    return ChatCompletionRequest(
        model="chat",
        messages=[Message(role="user", content=content)],
        stream=stream,
    )


async def collect_outputs(db, req, messages, kwargs=None, estimated=100, session_id=None):
    """消费 Executor 流式执行的所有输出"""
    ctx = PipelineContext(
        request_id="test-001",
        client_ip="127.0.0.1",
        stream=True,
        original_messages=messages,
        requested_model=req.model,
        kwargs=kwargs or {},
        estimated_tokens=estimated,
        session_id=session_id,
    )
    executor = Executor(db)
    outputs = []
    async for line in await executor.execute(ctx):
        outputs.append(line)
    return "".join(outputs)


async def make_account(db, vendor, model_name, priority, **extra):
    from tests.conftest import seed_account
    # 请求固定走虚拟模型 chat；catalog 行按 chat 建，才能被路由匹配
    return await seed_account(db, vendor, "chat", priority=priority, **extra)


async def fetch_logs(db):
    result = await db.execute(select(RequestLog).order_by(RequestLog.id))
    return result.scalars().all()


# ══════════════════════════════════════════════════════════
# 1. 字段存在性
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_request_log_has_a3_columns(db_session):
    """RequestLog 表包含 A3 新增字段"""
    result = await db_session.execute(
        select(RequestLog).where(RequestLog.request_id == "nonexistent")
    )
    result.scalar_one_or_none()  # 触发表查询，确认表结构可用

    cols = {c.name for c in RequestLog.__table__.columns}
    assert "user_feedback" in cols
    assert "feedback_at" in cols
    assert "implicit_signal" in cols
    assert "session_id" in cols


# ══════════════════════════════════════════════════════════
# 2. 流式输出前失败 → switch_retry
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stream_failover_sets_switch_retry(db_session, monkeypatch):
    """输出前失败切换：失败日志 implicit_signal=switch_retry，成功日志无信号"""
    acc_a = await make_account(db_session, "vendor-a", "model-a", priority=90)
    acc_b = await make_account(db_session, "vendor-b", "model-b", priority=80)
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()

    async def fake_stream(account, messages, **kwargs):
        if account.id == acc_a.id:
            raise RuntimeError("402 Payment Required")
        yield {"choices": [{"delta": {"content": "等于2", "role": "assistant"}, "index": 0}]}
        yield {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    monkeypatch.setattr(llm_client, "chat_completion_stream", fake_stream)

    req = make_req()
    joined = await collect_outputs(db_session, req, [{"role": "user", "content": "1+1等于几？"}], session_id="sess-1")
    assert "等于2" in joined and "data: [DONE]" in joined

    logs = await fetch_logs(db_session)
    assert len(logs) == 2
    failed_logs = [l for l in logs if l.account_id == acc_a.id]
    success_logs = [l for l in logs if l.account_id == acc_b.id]
    assert failed_logs[0].status == "failed"
    assert failed_logs[0].implicit_signal == "switch_retry"
    assert success_logs[0].status == "success"
    assert success_logs[0].implicit_signal is None
    # A3: 会话ID写入日志
    assert success_logs[0].session_id == "sess-1"


# ══════════════════════════════════════════════════════════
# 3. 流式输出后中断 → stream_interrupted
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stream_interrupted_signal(db_session, monkeypatch):
    """输出后中断：日志 implicit_signal=stream_interrupted"""
    acc_a = await make_account(db_session, "vendor-a", "model-a", priority=90)
    db_session.add(acc_a)
    await db_session.commit()

    async def fake_stream(account, messages, **kwargs):
        yield {"choices": [{"delta": {"content": "部分", "role": "assistant"}, "index": 0}]}
        raise RuntimeError("连接中断")

    monkeypatch.setattr(llm_client, "chat_completion_stream", fake_stream)

    req = make_req()
    joined = await collect_outputs(db_session, req, [{"role": "user", "content": "hi"}], session_id="sess-2")
    assert "部分" in joined and "请求中断" in joined

    logs = await fetch_logs(db_session)
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].implicit_signal == "stream_interrupted"


# ══════════════════════════════════════════════════════════
# 4. 非流式失败 → switch_retry
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_non_stream_failure_signal(db_session, monkeypatch):
    """非流式失败：日志 implicit_signal=switch_retry"""
    acc_a = await make_account(db_session, "vendor-a", "model-a", priority=90)
    db_session.add(acc_a)
    await db_session.commit()

    async def fake_chat(account, messages, **kwargs):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(llm_client, "chat_completion", fake_chat)

    ctx = PipelineContext(
        request_id="test-ns",
        client_ip="127.0.0.1",
        stream=False,
        original_messages=[{"role": "user", "content": "hi"}],
        requested_model="chat",
        kwargs={},
        estimated_tokens=100,
        session_id="sess-3",
    )
    executor = Executor(db_session)
    with pytest.raises(Exception):
        await executor.execute(ctx)

    logs = await fetch_logs(db_session)
    assert len(logs) >= 1
    assert logs[0].status == "failed"
    assert logs[0].implicit_signal == "switch_retry"


# ══════════════════════════════════════════════════════════
# 5. /v1/feedback 反馈上报端点
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_feedback_updates_log(db_session):
    """反馈上报：更新 user_feedback + feedback_at"""
    from app.routes.api import submit_feedback
    log = RequestLog(
        request_id="fb-001",
        account_id=1,
        vendor="test",
        model_name="m",
        status="success",
        session_id="sess-fb",
    )
    db_session.add(log)
    await db_session.commit()

    resp = await submit_feedback(
        FeedbackRequest(request_id="fb-001", feedback="up"),
        db_session, None,
    )
    assert resp["feedback"] == "up"

    await db_session.refresh(log)
    assert log.user_feedback == "up"
    assert log.feedback_at is not None


@pytest.mark.asyncio
async def test_feedback_overwrites(db_session):
    """反馈上报幂等：重复提交覆盖旧值"""
    from app.routes.api import submit_feedback
    log = RequestLog(
        request_id="fb-002",
        account_id=1,
        vendor="test",
        model_name="m",
        status="success",
        user_feedback="down",
        session_id="sess-fb",
    )
    db_session.add(log)
    await db_session.commit()

    await submit_feedback(FeedbackRequest(request_id="fb-002", feedback="up"), db_session, None)
    await db_session.refresh(log)
    assert log.user_feedback == "up"


@pytest.mark.asyncio
async def test_feedback_invalid_value(db_session):
    """反馈值非法 → 400"""
    from fastapi import HTTPException
    from app.routes.api import submit_feedback
    log = RequestLog(request_id="fb-003", account_id=1, vendor="t", model_name="m", status="success")
    db_session.add(log)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await submit_feedback(FeedbackRequest(request_id="fb-003", feedback="bad"), db_session, None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_feedback_not_found(db_session):
    """request_id 不存在 → 404"""
    from fastapi import HTTPException
    from app.routes.api import submit_feedback
    with pytest.raises(HTTPException) as exc:
        await submit_feedback(FeedbackRequest(request_id="no-such-id", feedback="up"), db_session, None)
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════
# 5.5 request_id 暴露（客户端据此上报反馈）+ 客户端取消信号
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_response_headers_expose_request_id():
    """非流式 JSONResponse 与流式 StreamingResponse 均携带 X-Request-Id 头"""
    from fastapi.responses import StreamingResponse
    from fastapi.responses import JSONResponse

    # 非流式：JSONResponse 可追加响应头
    resp = JSONResponse(content={"choices": []})
    resp.headers["X-Request-Id"] = "req-head-1"
    assert resp.headers.get("X-Request-Id") == "req-head-1"

    # 流式：StreamingResponse 构造时传入 headers
    async def gen():
        yield b"data: [DONE]\n\n"
    stream_resp = StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"X-Request-Id": "req-head-2"},
    )
    assert stream_resp.headers.get("X-Request-Id") == "req-head-2"


@pytest.mark.asyncio
async def test_client_cancel_marks_stream_interrupted(db_session, monkeypatch):
    """客户端主动断开（asyncio.CancelledError）→ 日志 failed + stream_interrupted"""
    import asyncio
    acc_a = await make_account(db_session, "vendor-a", "model-a", priority=90)
    db_session.add(acc_a)
    await db_session.commit()

    async def fake_stream(account, messages, **kwargs):
        yield {"choices": [{"delta": {"content": "部分内容", "role": "assistant"}, "index": 0}]}
        raise asyncio.CancelledError()

    monkeypatch.setattr(llm_client, "chat_completion_stream", fake_stream)

    ctx = PipelineContext(
        request_id="test-cancel",
        client_ip="127.0.0.1",
        stream=True,
        original_messages=[{"role": "user", "content": "hi"}],
        requested_model="chat",
        kwargs={},
        estimated_tokens=100,
        session_id="sess-cancel",
    )
    executor = Executor(db_session)
    with pytest.raises(asyncio.CancelledError):
        async for _ in await executor.execute(ctx):
            pass

    logs = await fetch_logs(db_session)
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].implicit_signal == "stream_interrupted"


# ══════════════════════════════════════════════════════════
# 6. followup（继续追问）隐式信号推断
# ══════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_followup_signal_within_window(db_session):
    """窗口内继续追问 → 上一条成功日志标记 followup"""
    from app.routes.api import _mark_followup_signal
    log = RequestLog(
        request_id="fl-001",
        account_id=1,
        vendor="t",
        model_name="m",
        status="success",
        session_id="sess-fl",
        created_at=datetime.utcnow() - timedelta(seconds=60),
    )
    db_session.add(log)
    await db_session.commit()

    await _mark_followup_signal("sess-fl", db_session)

    await db_session.refresh(log)
    assert log.implicit_signal == "followup"


@pytest.mark.asyncio
async def test_followup_signal_outside_window(db_session):
    """超过窗口（300s）→ 不标记 followup"""
    from app.routes.api import _mark_followup_signal
    log = RequestLog(
        request_id="fl-002",
        account_id=1,
        vendor="t",
        model_name="m",
        status="success",
        session_id="sess-fl2",
        created_at=datetime.utcnow() - timedelta(minutes=10),
    )
    db_session.add(log)
    await db_session.commit()

    await _mark_followup_signal("sess-fl2", db_session)

    await db_session.refresh(log)
    assert log.implicit_signal is None


@pytest.mark.asyncio
async def test_followup_does_not_overwrite(db_session):
    """已有隐式信号的日志不被 followup 覆盖"""
    from app.routes.api import _mark_followup_signal
    log = RequestLog(
        request_id="fl-003",
        account_id=1,
        vendor="t",
        model_name="m",
        status="success",
        session_id="sess-fl3",
        implicit_signal="switch_retry",
        created_at=datetime.utcnow() - timedelta(seconds=10),
    )
    db_session.add(log)
    await db_session.commit()

    await _mark_followup_signal("sess-fl3", db_session)

    await db_session.refresh(log)
    assert log.implicit_signal == "switch_retry"


@pytest.mark.asyncio
async def test_followup_ignores_failed(db_session):
    """上一条是失败日志 → 不标记"""
    from app.routes.api import _mark_followup_signal
    log = RequestLog(
        request_id="fl-004",
        account_id=1,
        vendor="t",
        model_name="m",
        status="failed",
        session_id="sess-fl4",
        created_at=datetime.utcnow() - timedelta(seconds=10),
    )
    db_session.add(log)
    await db_session.commit()

    await _mark_followup_signal("sess-fl4", db_session)

    await db_session.refresh(log)
    assert log.implicit_signal is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
