"""
流式请求账号自动切换单元测试

覆盖 stream_with_failover 的关键路径：
1. 账号在输出前失败（如402欠费）→ 自动切换下一个账号 → 正常输出 + [DONE]
2. 账号已输出后失败 → 不切换，返回 stream_error 事件
3. 所有账号均输出前失败 / 无可用账号 → 返回错误事件（绝不中断连接）
4. 切换场景下失败/成功账号的日志与扣费记录正确
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from app.models.database import Base, ModelAccount, SystemConfig, RequestLog
from app.routes.api import stream_with_failover, ChatCompletionRequest, Message
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


def make_req(content="1+1等于几？"):
    return ChatCompletionRequest(
        model="chat",
        messages=[Message(role="user", content=content)],
        stream=True,
    )


async def collect_outputs(db, req, messages, kwargs=None, estimated=100):
    """消费 stream_with_failover 的所有输出"""
    outputs = []
    async for line in stream_with_failover(
        db, req, messages, kwargs or {}, estimated, "127.0.0.1"
    ):
        outputs.append(line)
    return "".join(outputs)


def make_account(db, vendor, model_name, priority, **extra):
    acc = ModelAccount(
        vendor=vendor,
        model_name=model_name,
        api_key_encrypted=f"key-{vendor}",
        priority=priority,
        virtual_model="chat",
        balance_unit="token",
        balance_remaining=1000000,
        **extra,
    )
    return acc


@pytest.mark.asyncio
async def test_failover_before_output(db_session, monkeypatch):
    """账号A输出前失败（如402）→ 自动切换账号B → 正常输出 + [DONE] + 日志扣费正确"""
    acc_a = make_account(db_session, "vendor-a", "model-a", priority=90)
    acc_b = make_account(db_session, "vendor-b", "model-b", priority=80)
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()

    async def fake_stream(account, messages, **kwargs):
        if account.id == acc_a.id:
            raise RuntimeError("402 Payment Required")  # 输出前失败
        yield {"choices": [{"delta": {"content": "等于2", "role": "assistant"}, "index": 0}]}
        yield {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    monkeypatch.setattr(llm_client, "chat_completion_stream", fake_stream)

    req = make_req()
    joined = await collect_outputs(db_session, req, [{"role": "user", "content": "1+1等于几？"}])

    # 1. 正常输出且以 [DONE] 结束
    assert "等于2" in joined
    assert "data: [DONE]" in joined

    # 2. 账号A被标记冷却（failover 生效）
    await db_session.refresh(acc_a)
    assert acc_a.cool_down_until is not None

    # 3. 失败账号记 failed 日志，成功账号记 success 日志并正确扣费
    result = await db_session.execute(select(RequestLog).order_by(RequestLog.id))
    logs = result.scalars().all()
    assert len(logs) == 2
    failed_logs = [l for l in logs if l.account_id == acc_a.id]
    success_logs = [l for l in logs if l.account_id == acc_b.id]
    assert failed_logs and failed_logs[0].status == "failed"
    assert success_logs and success_logs[0].status == "success"
    await db_session.refresh(acc_b)
    assert acc_b.daily_used_tokens == 15


@pytest.mark.asyncio
async def test_no_failover_after_output(db_session, monkeypatch):
    """账号已输出后失败 → 不切换，返回 stream_error 事件（不输出 [DONE]）"""
    acc_a = make_account(db_session, "vendor-a", "model-a", priority=90)
    db_session.add(acc_a)
    await db_session.commit()

    async def fake_stream(account, messages, **kwargs):
        yield {"choices": [{"delta": {"content": "部分", "role": "assistant"}, "index": 0}]}
        raise RuntimeError("连接中断")  # 输出中失败

    monkeypatch.setattr(llm_client, "chat_completion_stream", fake_stream)

    req = make_req()
    joined = await collect_outputs(db_session, req, [{"role": "user", "content": "hi"}])

    assert "部分" in joined               # 已输出内容被正常转发
    assert "请求中断" in joined            # 返回错误事件
    assert "data: [DONE]" not in joined   # 不输出结束标记


@pytest.mark.asyncio
async def test_all_fail_before_output(db_session, monkeypatch):
    """所有账号均输出前失败 → 返回 no_available_account 错误事件（不中断连接）"""
    acc_a = make_account(db_session, "vendor-a", "model-a", priority=90)
    db_session.add(acc_a)
    await db_session.commit()

    async def fake_stream(account, messages, **kwargs):
        if account.id == acc_a.id:
            raise RuntimeError("always fail")
        yield None  # 仅用于使函数成为异步生成器（永不执行到）

    monkeypatch.setattr(llm_client, "chat_completion_stream", fake_stream)

    req = make_req()
    joined = await collect_outputs(db_session, req, [{"role": "user", "content": "hi"}])

    assert "no_available_account" in joined   # 返回 no_available_account 错误事件
    assert "always fail" in joined            # 携带最终错误信息
    assert "data: [DONE]" not in joined


@pytest.mark.asyncio
async def test_no_available_account(db_session):
    """无可用账号 → 返回 no_available_account 错误事件（不中断连接）"""
    req = make_req()
    joined = await collect_outputs(db_session, req, [{"role": "user", "content": "hi"}])

    assert "没有可用账号" in joined
    assert "data: [DONE]" not in joined


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
