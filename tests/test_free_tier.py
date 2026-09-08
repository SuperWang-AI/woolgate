"""
免费模型目录（A7）+ 免费 tier 向导（A1）单元测试

覆盖：
1. 目录完整性：≥8 家厂商，每厂商 base_url/模型/入口/步骤/额度说明 非空
2. auto_configure 全流程：建账号 → 同步模型目录 → 能力描述 → 计算向量 → 启用
3. 幂等：重复配置同厂商同模型 → 跳过不重复建号
4. 真实模型优先：探测到的真实模型 ∩ 目录模型
5. 异常：空 Key / 未知厂商 / Cloudflare 缺 Account ID
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, ModelAccount, ModelCatalog, SystemConfig
from app.services.free_tier_catalog import FREE_TIER_VENDORS, get_vendor, list_vendors, FreeTierService


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


class FakeEmbed:
    """伪 EmbeddingService：固定 8 维向量"""

    def __init__(self, *args, **kwargs):
        pass

    async def embed(self, text):
        return [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


# ───────────────────────── 目录完整性 ─────────────────────────

def test_catalog_has_at_least_8_vendors():
    """目录覆盖 ≥8 家厂商（A7 验收）"""
    assert len(FREE_TIER_VENDORS) >= 8, f"免费模型目录仅 {len(FREE_TIER_VENDORS)} 家，不足 8 家"
    assert len(list_vendors()) == len(FREE_TIER_VENDORS)


def test_catalog_each_vendor_complete():
    """每家厂商必须：base_url / 模型列表 / 获取入口 / 步骤 / 额度说明 齐全"""
    for v in FREE_TIER_VENDORS:
        assert v["id"], f"{v['name']} 缺 id"
        assert v["base_url"].startswith("http"), f"{v['name']} base_url 非法"
        assert v["models"], f"{v['name']} 无免费模型"
        assert v["signup_url"].startswith("http"), f"{v['name']} 缺获取入口"
        assert len(v["steps"]) >= 1, f"{v['name']} 缺获取步骤"
        assert v["quota_note"], f"{v['name']} 缺额度说明"
        for m in v["models"]:
            assert m["id"], f"{v['name']} 存在空模型 id"
            assert m["capability"], f"{v['name']} / {m['id']} 缺能力描述"
            assert m["examples"], f"{v['name']} / {m['id']} 缺示例（向量计算依赖）"
    # id 唯一
    ids = [v["id"] for v in FREE_TIER_VENDORS]
    assert len(ids) == len(set(ids)), "厂商 id 重复"


def test_get_vendor_lookup():
    """按 id 查找与未知 id 容错"""
    assert get_vendor("groq")["name"] == "Groq"
    assert get_vendor("not-exist") is None


# ───────────────────────── auto_configure 全流程 ─────────────────────────

@pytest.mark.asyncio
async def test_auto_configure_full_flow(db_session, monkeypatch):
    """向导配置全流程：建账号 + 同步模型 + 能力描述 + 向量 + 启用"""
    # mock 模型探测（返回目录内模型）
    async def fake_fetch_models(account):
        return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    res = await svc.auto_configure("groq", "sk-test-key-123")

    assert res["vendor"] == "Groq"
    assert len(res["created_accounts"]) == 2
    assert res["models_synced"] == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    assert res["errors"] == []

    # 账号落库 + 启用
    accounts = (await db_session.execute(select(ModelAccount))).scalars().all()
    assert len(accounts) == 2
    for acc in accounts:
        assert acc.is_enable is True
        assert acc.vendor == "Groq"
        assert acc.base_url == "https://api.groq.com/openai/v1"
        assert acc.api_key_encrypted  # 已加密

    # 模型目录同步 + 能力描述 + 向量
    catalogs = (await db_session.execute(select(ModelCatalog))).scalars().all()
    assert len(catalogs) == 2
    for cat in catalogs:
        assert cat.capability_description
        assert cat.examples
        assert cat.embedding_vector == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        assert cat.is_active is True


@pytest.mark.asyncio
async def test_auto_configure_idempotent(db_session, monkeypatch):
    """幂等：同厂商同模型重复配置 → 跳过，不重复建号"""
    async def fake_fetch_models(account):
        return ["llama-3.3-70b-versatile"]

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    await svc.auto_configure("groq", "sk-key-1")
    res2 = await svc.auto_configure("groq", "sk-key-2")

    assert res2["created_accounts"] == []
    assert res2["skipped"] == ["llama-3.3-70b-versatile"]
    accounts = (await db_session.execute(select(ModelAccount))).scalars().all()
    assert len(accounts) == 1


@pytest.mark.asyncio
async def test_auto_configure_real_models_priority(db_session, monkeypatch):
    """真实模型优先：探测返回 目录∩真实 的交集"""
    async def fake_fetch_models(account):
        return ["llama-3.3-70b-versatile", "some-new-model-xyz"]  # 一个在目录内，一个不在

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    res = await svc.auto_configure("groq", "sk-key-1")

    # 只取交集（真实模型里有目录外的新模型也不盲配）
    assert res["models_synced"] == ["llama-3.3-70b-versatile"]
    assert len(res["created_accounts"]) == 1


@pytest.mark.asyncio
async def test_auto_configure_fallback_to_catalog_when_probe_fails(db_session, monkeypatch):
    """探测失败（无网络/接口 404）→ 回退用目录模型"""
    async def fake_fetch_models(account):
        return []

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    res = await svc.auto_configure("zhipu", "sk-key-1")

    assert res["models_synced"] == ["glm-4-flash"]
    assert len(res["created_accounts"]) == 1


@pytest.mark.asyncio
async def test_auto_configure_balance_support(db_session, monkeypatch):
    """支持余额的厂商（硅基流动）配置后自动获取余额"""
    async def fake_fetch_models(account):
        return ["Qwen/Qwen2.5-7B-Instruct"]

    async def fake_fetch_balance(account):
        return "currency", 14.0

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.balance.fetch_balance", fake_fetch_balance)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    res = await svc.auto_configure("siliconflow", "sk-key-1")

    assert res["balance"] == ("currency", 14.0)


# ───────────────────────── 异常与参数 ─────────────────────────

@pytest.mark.asyncio
async def test_auto_configure_unknown_vendor(db_session):
    svc = FreeTierService(db_session)
    with pytest.raises(ValueError, match="未知厂商"):
        await svc.auto_configure("not-exist", "sk-key-1")


@pytest.mark.asyncio
async def test_auto_configure_empty_key(db_session):
    svc = FreeTierService(db_session)
    with pytest.raises(ValueError, match="API Key"):
        await svc.auto_configure("groq", "   ")


@pytest.mark.asyncio
async def test_auto_configure_cloudflare_requires_account_id(db_session, monkeypatch):
    """Cloudflare 需要 Account ID 填充 base_url 模板"""
    svc = FreeTierService(db_session)
    with pytest.raises(ValueError, match="Account ID"):
        await svc.auto_configure("cloudflare", "sk-key-1", extra={})


@pytest.mark.asyncio
async def test_auto_configure_cloudflare_with_account_id(db_session, monkeypatch):
    """Cloudflare 填了 Account ID 后 base_url 正确替换"""
    async def fake_fetch_models(account):
        return []

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    res = await svc.auto_configure("cloudflare", "sk-key-1", extra={"account_id": "abc123"})

    assert res["created_accounts"]
    accounts = (await db_session.execute(select(ModelAccount))).scalars().all()
    assert accounts[0].base_url == "https://api.cloudflare.com/client/v4/accounts/abc123/ai/v1"
