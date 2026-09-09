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
from app.services.free_tier_catalog import FREE_TIER_VENDORS, get_vendor, list_vendors, FreeTierService, vendor_matches


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


# ───────────────────────── 别名匹配（已接入/幂等） ─────────────────────────

def test_vendor_matches_alias():
    """同一厂商不同写法应匹配"""
    assert vendor_matches("月之暗面 (Moonshot)", "moonshot")
    assert vendor_matches("月之暗面 Kimi", "moonshot")
    assert vendor_matches("Kimi", "moonshot")
    assert vendor_matches("硅基流动 (SiliconFlow)", "siliconflow")
    assert vendor_matches("智谱", "zhipu")
    assert vendor_matches("阿里百炼 (Qwen)", "gemini") is False  # 不同厂商不误配
    assert vendor_matches("", "groq") is False
    assert vendor_matches("Groq", "groq")


@pytest.mark.asyncio
async def test_auto_configure_dedup_by_alias(db_session, monkeypatch):
    """真实场景：库里已有 '月之暗面 (Moonshot)' 账号 → 向导配置 moonshot 不重复建号"""
    # 预置已有账号（模拟账号管理里的月之暗面）
    existing = ModelAccount(
        vendor="月之暗面 (Moonshot)",
        model_name="kimi-k2.6",
        api_key_encrypted="enc-old-key",
        virtual_model="chat",
        is_enable=True,
    )
    db_session.add(existing)
    await db_session.commit()

    async def fake_fetch_models(account):
        return ["kimi-k2.6", "moonshot-v1-8k"]

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    res = await svc.auto_configure("moonshot", "sk-new-key")

    # kimi-k2.6 已存在（别名匹配）→ 跳过；moonshot-v1-8k 新建
    assert res["skipped"] == ["kimi-k2.6"]
    assert len(res["created_accounts"]) == 1
    assert res["models_synced"] == ["moonshot-v1-8k"]

    accounts = (await db_session.execute(select(ModelAccount))).scalars().all()
    assert len(accounts) == 2  # 原账号 + 1 个新账号


# ─────────────── 合并目录（内置 + DB 用户覆盖）───────────────

@pytest.mark.asyncio
async def test_merged_vendors_no_override(db_session):
    """无覆盖记录时，合并目录 == 内置目录"""
    from app.services.free_tier_catalog import _merged_vendors, FREE_TIER_VENDORS

    merged = await _merged_vendors(db_session)
    assert len(merged) == len(FREE_TIER_VENDORS)
    assert [v["id"] for v in merged] == [v["id"] for v in FREE_TIER_VENDORS]


@pytest.mark.asyncio
async def test_merged_vendors_add_custom(db_session):
    """自定义厂商追加到合并目录"""
    from app.services.free_tier_catalog import _merged_vendors, list_vendors_merged
    from app.models.database import VendorOverride
    import json as _json

    custom = {
        "id": "myvendor",
        "name": "MyVendor",
        "icon": "🤖",
        "tag": "国内 · 自定义",
        "region": "国内",
        "base_url": "https://api.myvendor.com/v1",
        "models": [{"id": "my-model", "display": "My Model", "capability": "测试", "tags": ["chat"], "examples": ["你好"]}],
        "signup_url": "https://myvendor.com",
        "steps": ["注册", "拿 Key"],
        "balance_support": False,
        "quota_note": "自定义测试",
    }
    db_session.add(VendorOverride(id="myvendor", vendor_json=_json.dumps(custom, ensure_ascii=False)))
    await db_session.commit()

    merged = await _merged_vendors(db_session)
    ids = [v["id"] for v in merged]
    assert "myvendor" in ids
    assert ids[-1] == "myvendor"  # 追加在末尾
    brief = await list_vendors_merged(db_session)
    assert any(b["id"] == "myvendor" for b in brief)


@pytest.mark.asyncio
async def test_merged_vendors_override_builtin(db_session):
    """覆盖内置厂商：名称/额度说明以 DB 为准"""
    from app.services.free_tier_catalog import _merged_vendors, get_vendor_merged
    from app.models.database import VendorOverride
    import json as _json

    override = {
        "id": "deepseek",
        "name": "DeepSeek（已覆盖）",
        "icon": "🐋",
        "tag": "国内 · 极低价",
        "region": "国内",
        "base_url": "https://api.deepseek.com/v1",
        "models": [{"id": "deepseek-chat", "display": "V3", "capability": "c", "tags": ["chat"], "examples": ["hi"]}],
        "signup_url": "https://platform.deepseek.com/",
        "steps": ["s1"],
        "balance_support": True,
        "quota_note": "覆盖后的额度说明",
    }
    db_session.add(VendorOverride(id="deepseek", vendor_json=_json.dumps(override, ensure_ascii=False)))
    await db_session.commit()

    merged = await _merged_vendors(db_session)
    ds = next(v for v in merged if v["id"] == "deepseek")
    assert ds["name"] == "DeepSeek（已覆盖）"
    assert ds["quota_note"] == "覆盖后的额度说明"
    assert len(merged) == len(__import__("app.services.free_tier_catalog", fromlist=["FREE_TIER_VENDORS"]).FREE_TIER_VENDORS)

    full = await get_vendor_merged(db_session, "deepseek")
    assert full["name"] == "DeepSeek（已覆盖）"


@pytest.mark.asyncio
async def test_merged_vendors_disable_builtin(db_session):
    """停用标记（is_deleted=True）从合并目录隐藏内置厂商"""
    from app.services.free_tier_catalog import _merged_vendors
    from app.models.database import VendorOverride

    db_session.add(VendorOverride(id="groq", vendor_json="{}", is_deleted=True))
    await db_session.commit()

    merged = await _merged_vendors(db_session)
    assert all(v["id"] != "groq" for v in merged)


# ───────────────────────── Key 决策（留空沿用 / 填写统一更换） ─────────────────────────

@pytest.mark.asyncio
async def test_auto_configure_key_reuse_when_blank(db_session, monkeypatch):
    """留空 Key → 沿用已有 Key：新增模型用旧 Key，已有模型跳过，keys_updated 为空"""
    state = {"n": 1}

    async def fake_fetch_models(account):
        # 第一次探测 1 个模型，第二次探测 2 个（模拟用户之后新增了模型）
        return ["llama-3.3-70b-versatile"] if state["n"] == 1 else ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    res1 = await svc.auto_configure("groq", "sk-old-1")
    assert len(res1["created_accounts"]) == 1

    state["n"] = 2
    res2 = await svc.auto_configure("groq", "")
    assert res2["skipped"] == ["llama-3.3-70b-versatile"]
    assert res2["created_accounts"] == ["Groq / llama-3.1-8b-instant"]
    assert res2["keys_updated"] == []

    from app.utils.encryption import encryption_service
    rows = (await db_session.execute(select(ModelAccount))).scalars().all()
    keys = {r.model_name: encryption_service.decrypt(r.api_key_encrypted) for r in rows}
    assert keys == {"llama-3.3-70b-versatile": "sk-old-1", "llama-3.1-8b-instant": "sk-old-1"}


@pytest.mark.asyncio
async def test_auto_configure_key_replace_when_new(db_session, monkeypatch):
    """填写新 Key → 统一更换该厂商全部已有模型的 Key，新增模型用新 Key"""
    async def fake_fetch_models(account):
        return ["llama-3.3-70b-versatile"]

    monkeypatch.setattr("app.services.balance.fetch_models", fake_fetch_models)
    monkeypatch.setattr("app.services.embedding.EmbeddingService", FakeEmbed)

    svc = FreeTierService(db_session)
    await svc.auto_configure("groq", "sk-old-1")

    res = await svc.auto_configure("groq", "sk-new-2")
    assert res["skipped"] == ["llama-3.3-70b-versatile"]
    assert res["keys_updated"] == ["llama-3.3-70b-versatile"]

    from app.utils.encryption import encryption_service
    rows = (await db_session.execute(select(ModelAccount))).scalars().all()
    for r in rows:
        assert encryption_service.decrypt(r.api_key_encrypted) == "sk-new-2"
