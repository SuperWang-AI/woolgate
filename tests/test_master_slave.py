"""主从数据语义单元测试（T5 部分）

覆盖决策单 #1/#3 的核心语义：
1. ensure_model 同模型多账号 → 各建一行（不再全局判存在）
2. 第二行复制原型行的能力/示例/单价/向量（不重算）
3. get_by_account_model 按 (account_id, model_name) 精确查
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, ModelAccount, ModelCatalog, SystemConfig
from app.services.model_catalog_service import ModelCatalogService


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


@pytest.mark.asyncio
async def test_ensure_model_master_slave_same_model_two_accounts(db_session):
    """同一模型在两个账号下 → 各建一行，互不覆盖"""
    acc_a = ModelAccount(vendor="厂商A", default_model_name="m-1", api_key_encrypted="k-a")
    acc_b = ModelAccount(vendor="厂商B", default_model_name="m-1", api_key_encrypted="k-b")
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()

    svc = ModelCatalogService(db_session)
    row_a = await svc.ensure_model("m-1", "厂商A", account_id=acc_a.id)
    row_b = await svc.ensure_model("m-1", "厂商B", account_id=acc_b.id)

    # 各账号一行
    result = await db_session.execute(
        select(ModelCatalog).where(ModelCatalog.model_name == "m-1")
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert {r.account_id for r in rows} == {acc_a.id, acc_b.id}
    # 能力描述归属各自厂商（原型行复制 vendor 保留各自传入）
    assert row_a.vendor == "厂商A"
    assert row_b.vendor == "厂商B"


@pytest.mark.asyncio
async def test_ensure_model_proto_copy_without_recompute(db_session):
    """第二行复制原型行的能力/示例/单价/向量（不重算）"""
    acc_a = ModelAccount(vendor="厂商A", default_model_name="m-2", api_key_encrypted="k-a")
    acc_b = ModelAccount(vendor="厂商B", default_model_name="m-2", api_key_encrypted="k-b")
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()

    svc = ModelCatalogService(db_session)
    row_a = await svc.ensure_model("m-2", "厂商A", account_id=acc_a.id)
    # 给原型行造数据
    row_a.capability_description = "擅长编程与算法"
    row_a.examples = ["写一个快排", "解释递归"]
    row_a.input_price = 1.5
    row_a.output_price = 3.0
    row_a.embedding_vector = [0.1, 0.2, 0.3]
    await db_session.commit()

    row_b = await svc.ensure_model("m-2", "厂商B", account_id=acc_b.id)

    assert row_b.id != row_a.id
    assert row_b.capability_description == "擅长编程与算法"
    assert row_b.examples == ["写一个快排", "解释递归"]
    assert row_b.input_price == 1.5
    assert row_b.output_price == 3.0
    assert row_b.embedding_vector == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_get_by_account_model(db_session):
    """按 (account_id, model_name) 精确查本账号行"""
    acc_a = ModelAccount(vendor="厂商A", default_model_name="m-3", api_key_encrypted="k-a")
    acc_b = ModelAccount(vendor="厂商B", default_model_name="m-3", api_key_encrypted="k-b")
    db_session.add_all([acc_a, acc_b])
    await db_session.commit()

    svc = ModelCatalogService(db_session)
    await svc.ensure_model("m-3", "厂商A", account_id=acc_a.id)
    await svc.ensure_model("m-3", "厂商B", account_id=acc_b.id)

    got_a = await svc.get_by_account_model(acc_a.id, "m-3")
    got_b = await svc.get_by_account_model(acc_b.id, "m-3")
    assert got_a is not None and got_b is not None
    assert got_a.id != got_b.id
    assert await svc.get_by_account_model(acc_a.id, "不存在的模型") is None
