"""
账号路由调度器单元测试（M5 清理后：覆盖存活方法）

- _filter_available_accounts: 启用/模型匹配/冷却/额度过滤
- _check_quota_sufficient: token / currency 双口径
- _infer_previous_account: 会话粘性
- mark_account_failed: 失败冷却
- deduct_quota: 本地用量累加
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, ModelAccount, SystemConfig
from app.services.router import AccountRouter
from tests.conftest import seed_account


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
        # 初始化系统配置
        config = SystemConfig(id=1)
        session.add(config)
        await session.commit()

        yield session


@pytest.mark.asyncio
async def test_filter_available_returns_only_enabled_matching(db_session):
    """过滤：仅返回启用 + 匹配模型 + 未冷却 + 额度充足的账号"""
    acc = await seed_account(db_session, "deepseek", "deepseek-chat",
                             balance_unit="token", balance_remaining=100000)
    await db_session.flush()
    router = AccountRouter(db_session)

    available = await router._filter_available_accounts("deepseek-chat", 1000)
    assert len(available) == 1
    assert available[0].id == acc.id


@pytest.mark.asyncio
async def test_filter_excludes_other_model_and_disabled(db_session):
    """过滤：其他模型、停用账号被排除"""
    acc_a = await seed_account(db_session, "deepseek", "deepseek-chat")
    acc_b = await seed_account(db_session, "moonshot", "kimi-k2.6")
    acc_b.is_enable = False
    await db_session.flush()
    router = AccountRouter(db_session)

    available = await router._filter_available_accounts("deepseek-chat", 1000)
    assert [a.id for a in available] == [acc_a.id]


@pytest.mark.asyncio
async def test_filter_excludes_cooling_account(db_session):
    """过滤：冷却中的账号被排除"""
    acc = await seed_account(db_session, "deepseek", "deepseek-chat")
    acc.cool_down_until = datetime.utcnow() + timedelta(seconds=300)
    await db_session.flush()
    router = AccountRouter(db_session)

    available = await router._filter_available_accounts("deepseek-chat", 1000)
    assert available == []


@pytest.mark.asyncio
async def test_filter_excludes_insufficient_quota(db_session):
    """过滤：额度不足以覆盖预估 token 的账号被排除"""
    await seed_account(db_session, "deepseek", "deepseek-chat",
                       balance_unit="token", balance_remaining=100)
    await db_session.flush()
    router = AccountRouter(db_session)

    available = await router._filter_available_accounts("deepseek-chat", 1000)
    assert available == []


@pytest.mark.asyncio
async def test_quota_sufficient_token_account(db_session):
    """额度预判：token 口径按 剩余 - 当日用量 >= 预估 判断"""
    router = AccountRouter(db_session)
    acc = ModelAccount(balance_unit="token", balance_remaining=1000,
                       daily_used_tokens=200, vendor="deepseek")
    assert router._check_quota_sufficient(acc, 500) is True
    assert router._check_quota_sufficient(acc, 900) is False


@pytest.mark.asyncio
async def test_quota_sufficient_currency_account(db_session):
    """额度预判：currency 口径按预估金额判断"""
    router = AccountRouter(db_session)
    acc = ModelAccount(balance_unit="currency", balance_remaining=1.0,
                       daily_used_currency=0.2, currency_rate=2.0, vendor="deepseek")
    # 预估金额 = 1000 * 2 / 1M = 0.002；剩余 0.8 → 充足
    assert router._check_quota_sufficient(acc, 1000) is True
    # 预估金额 = 500000 * 2 / 1M = 1.0；剩余 0.8 → 不足
    assert router._check_quota_sufficient(acc, 500000) is False


@pytest.mark.asyncio
async def test_quota_unlimited_when_balance_none(db_session):
    """额度预判：无初始额度（未同步余额）不限制"""
    router = AccountRouter(db_session)
    acc = ModelAccount(balance_remaining=None, vendor="deepseek")
    assert router._check_quota_sufficient(acc, 999999) is True


@pytest.mark.asyncio
async def test_mark_account_failed_sets_cooldown(db_session):
    """失败冷却：mark_account_failed 设置 cool_down_until"""
    acc = await seed_account(db_session, "deepseek", "deepseek-chat")
    acc.cool_down_seconds = 60
    await db_session.flush()
    router = AccountRouter(db_session)

    await router.mark_account_failed(acc.id)
    acc2 = await db_session.get(ModelAccount, acc.id)
    assert acc2.cool_down_until is not None
    assert acc2.cool_down_until > datetime.utcnow()


@pytest.mark.asyncio
async def test_deduct_quota_accumulates_local_usage(db_session):
    """记账：本地用量与累计统计累加"""
    acc = await seed_account(db_session, "deepseek", "deepseek-chat",
                             balance_unit="token", balance_remaining=100000)
    await db_session.flush()
    router = AccountRouter(db_session)

    await router.deduct_quota(acc.id, 100, 50)
    acc2 = await db_session.get(ModelAccount, acc.id)
    assert acc2.daily_used_tokens == 150
    assert acc2.total_prompt_tokens == 100
    assert acc2.total_completion_tokens == 50


@pytest.mark.asyncio
async def test_infer_previous_account_returns_last_success(db_session):
    """会话粘性：返回最近成功使用的启用账号"""
    from app.models.database import RequestLog
    acc = await seed_account(db_session, "deepseek", "deepseek-chat",
                             balance_unit="token", balance_remaining=100000)
    await db_session.flush()
    router = AccountRouter(db_session)

    # 预置一条最近的成功请求日志
    log = RequestLog(account_id=acc.id, vendor="deepseek", model_name="deepseek-chat",
                     status="success", created_at=datetime.utcnow())
    db_session.add(log)
    await db_session.commit()

    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮你？"},
    ]
    prev = await router._infer_previous_account(messages, "deepseek-chat", 1000)
    assert prev is not None
    assert prev.id == acc.id


@pytest.mark.asyncio
async def test_infer_previous_account_returns_none_for_new_chat(db_session):
    """会话粘性：无 assistant 消息（新对话）不推断"""
    router = AccountRouter(db_session)
    messages = [{"role": "user", "content": "你好"}]
    prev = await router._infer_previous_account(messages, "deepseek-chat", 1000)
    assert prev is None
