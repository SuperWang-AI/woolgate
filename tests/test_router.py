"""
核心路由调度算法单元测试
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, ModelAccount, SystemConfig
from app.services.router import AccountRouter


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
async def test_sequential_strategy(db_session):
    """测试顺序耗尽策略：高优先级账号优先选中"""
    # 创建3个不同优先级的账号
    accounts = [
        ModelAccount(
            vendor="test", model_name="test-model", api_key_encrypted="key1",
            priority=30, balance_unit="token", balance_remaining=1000000,
            virtual_model="test-model",
        ),
        ModelAccount(
            vendor="test", model_name="test-model", api_key_encrypted="key2",
            priority=70, balance_unit="token", balance_remaining=1000000,
            virtual_model="test-model",
        ),
        ModelAccount(
            vendor="test", model_name="test-model", api_key_encrypted="key3",
            priority=50, balance_unit="token", balance_remaining=1000000,
            virtual_model="test-model",
        ),
    ]
    
    for acc in accounts:
        db_session.add(acc)
    await db_session.commit()
    
    # 使用顺序策略选择账号
    router = AccountRouter(db_session)
    selected = await router.select_account("test-model", estimated_tokens=1000, strategy="sequential")
    
    assert selected is not None
    assert selected.priority == 70  # 应该选中最高优先级


@pytest.mark.asyncio
async def test_quota_filtering(db_session):
    """测试额度不足的账号被过滤"""
    # 创建一个额度不足的账号
    account = ModelAccount(
        vendor="test", model_name="test-model", api_key_encrypted="key",
        priority=50, balance_unit="token", balance_remaining=1000, daily_used_tokens=900,
        virtual_model="test-model",
    )
    db_session.add(account)
    await db_session.commit()
    
    router = AccountRouter(db_session)
    # 请求需要200 tokens，但账号只剩100
    selected = await router.select_account("test-model", estimated_tokens=200)
    
    assert selected is None  # 没有可用账号


@pytest.mark.asyncio
async def test_cool_down_filtering(db_session):
    """测试冷却中的账号被过滤"""
    # 创建一个在冷却中的账号
    account = ModelAccount(
        vendor="test", model_name="test-model", api_key_encrypted="key",
        priority=50, balance_unit="token", balance_remaining=1000000,
        virtual_model="test-model",
        cool_down_until=datetime.utcnow() + timedelta(minutes=5)
    )
    db_session.add(account)
    await db_session.commit()
    
    router = AccountRouter(db_session)
    selected = await router.select_account("test-model", estimated_tokens=1000)
    
    assert selected is None  # 冷却中的账号不可用


@pytest.mark.asyncio
async def test_ollama_skip_quota_check(db_session):
    """测试Ollama账号跳过额度检查"""
    # 创建一个Ollama账号（额度为0）
    account = ModelAccount(
        vendor="ollama", model_name="llama3", api_key_encrypted="key",
        priority=50, balance_unit="token", balance_remaining=0,
        virtual_model="llama3",
    )
    db_session.add(account)
    await db_session.commit()
    
    router = AccountRouter(db_session)
    selected = await router.select_account("llama3", estimated_tokens=1000)
    
    assert selected is not None  # Ollama不检查额度
    assert selected.vendor == "ollama"


@pytest.mark.asyncio
async def test_deduct_quota_token_mode(db_session):
    """测试消耗统计：token + 金额"""
    account = ModelAccount(
        vendor="test", model_name="test-model", api_key_encrypted="key",
        balance_unit="token", balance_remaining=10000,
        currency_rate=2.0
    )
    db_session.add(account)
    await db_session.commit()
    
    router = AccountRouter(db_session)
    wool_value, is_free = await router.deduct_quota(account.id, prompt_tokens=1000, completion_tokens=2000)
    
    # 验证当日用量与累计用量统计
    await db_session.refresh(account)
    assert account.daily_used_tokens == 3000
    assert account.total_prompt_tokens == 1000
    assert account.total_completion_tokens == 2000
    # 金额 = 3000 * 2.0 / 1M = 0.006
    assert abs(account.daily_used_currency - 0.006) < 0.0001
    assert abs(account.total_used_currency - 0.006) < 0.0001
    # 不再计算羊毛金额
    assert wool_value == 0.0
    assert is_free is True


@pytest.mark.asyncio
async def test_deduct_quota_ollama_no_value(db_session):
    """测试Ollama消耗统计：不计算金额"""
    account = ModelAccount(
        vendor="ollama", model_name="llama3", api_key_encrypted="key",
        balance_unit="token", balance_remaining=0
    )
    db_session.add(account)
    await db_session.commit()
    
    router = AccountRouter(db_session)
    wool_value, is_free = await router.deduct_quota(account.id, prompt_tokens=1000, completion_tokens=2000)
    
    await db_session.refresh(account)
    assert wool_value == 0.0
    assert is_free is True
    assert account.daily_used_tokens == 3000


@pytest.mark.asyncio
async def test_round_robin_strategy(db_session):
    """测试轮询策略：账号轮流选择"""
    # 创建3个相同优先级的账号
    for i in range(3):
        account = ModelAccount(
            vendor="test", model_name="test-model", api_key_encrypted=f"key{i}",
            priority=50, balance_unit="token", balance_remaining=1000000,
            virtual_model="test-model",
        )
        db_session.add(account)
    await db_session.commit()
    
    router = AccountRouter(db_session)
    
    # 连续选择3次，应该轮流选中不同账号
    selected_ids = []
    for _ in range(3):
        selected = await router.select_account("test-model", estimated_tokens=1000, strategy="round_robin")
        selected_ids.append(selected.id)
    
    # 验证选中了不同的账号
    assert len(set(selected_ids)) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
