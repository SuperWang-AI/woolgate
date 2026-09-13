"""
A2 启动意图引导测试（v2.1，09-11 重设计）

覆盖：
1. SystemConfig 表包含 onboarded / onboard_profile 字段
2. 引导映射（纯函数 build_onboard_data）：
   - 个人自用省钱 + 免费模型优先 + 都还没有 → hybrid / free-first / summary（云端免费摘要）
   - 企业私有化部署 + 本地模型优先 + 本地就绪 → hybrid / cost-first / summary（本地摘要）+ ollama 开启
   - 省钱方式选本地 → ollama_enabled=True
   - 已有资源含本地（即使省钱选免费）→ 顺带开启 ollama
   - 智能均衡为默认底座：无论省钱方式，路由恒 hybrid、上下文恒 summary（默认开启压缩）
3. 应用后 profile 名称中文组合正确
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select, text

from app.models.database import Base, SystemConfig
from app.ui.admin import build_onboard_data


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


# ══════════════════════════════════════════════════════════
# 1. 字段存在性
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_system_config_has_onboard_columns(db_session):
    """SystemConfig 表包含 A2 引导字段"""
    cols = {c.name for c in SystemConfig.__table__.columns}
    assert "onboarded" in cols
    assert "onboard_profile" in cols


# ══════════════════════════════════════════════════════════
# 2. 引导映射（纯函数）
# ══════════════════════════════════════════════════════════

def test_personal_free_none_profile():
    """个人自用省钱 + 免费模型优先 + 都还没有 → hybrid / free-first / summary（云端免费摘要）"""
    data, profile = build_onboard_data({"way": "personal", "saving": "free", "resource": "none"})
    assert data["router_strategy"] == "hybrid"
    assert data["selector_strategy"] == "free-first"
    assert data["context_strategy"] == "summary"
    assert data["context_config_json"]["summary_provider"] == "cloud"
    assert data["context_config_json"]["summary_model"] == "glm-4-flash"
    assert data["onboarded"] is True
    assert "ollama_enabled" not in data  # 无本地资源不开启
    assert profile == "个人自用省钱·免费模型优先·都还没有"


def test_team_local_local_profile():
    """企业私有化部署 + 本地模型优先 + 本地大模型就绪 → hybrid / cost-first / summary（本地摘要）+ ollama 开启"""
    data, profile = build_onboard_data({"way": "team", "saving": "local", "resource": "local"})
    assert data["router_strategy"] == "hybrid"
    assert data["selector_strategy"] == "cost-first"
    assert data["context_strategy"] == "summary"
    assert data["context_config_json"]["summary_provider"] == "local"
    assert data["ollama_enabled"] is True
    assert profile == "企业私有化部署·本地模型优先·本地大模型就绪"


def test_local_saving_enables_ollama():
    """省钱方式选本地 → ollama_enabled=True + 本地摘要"""
    data, _ = build_onboard_data({"way": "personal", "saving": "local", "resource": "none"})
    assert data["ollama_enabled"] is True
    assert data["context_strategy"] == "summary"
    assert data["context_config_json"]["summary_provider"] == "local"


def test_local_resource_enables_ollama():
    """已有资源含本地大模型（即使省钱选免费）→ 顺带开启 ollama，摘要仍走云端免费"""
    data, _ = build_onboard_data({"way": "personal", "saving": "free", "resource": "local"})
    assert data["ollama_enabled"] is True
    assert data["context_strategy"] == "summary"
    assert data["context_config_json"]["summary_provider"] == "cloud"


def test_key_resource_no_ollama():
    """已有厂商 API Key（无本地）→ 不强制开启 ollama"""
    data, _ = build_onboard_data({"way": "personal", "saving": "free", "resource": "key"})
    assert "ollama_enabled" not in data
    assert data["context_strategy"] == "summary"


def test_smart_base_always_on():
    """智能均衡为默认底座：无论省钱方式，路由恒 hybrid、上下文恒 summary（压缩默认开启）"""
    for saving in ("free", "local"):
        data, _ = build_onboard_data({"way": "personal", "saving": saving, "resource": "none"})
        assert data["router_strategy"] == "hybrid"
        assert data["context_strategy"] == "summary"


def test_router_config_has_hybrid_thresholds():
    """hybrid 路由配置带智能路由默认阈值（0.65/0.55）"""
    data, _ = build_onboard_data({"way": "personal", "saving": "free", "resource": "none"})
    assert data["router_config_json"] == {"threshold_high": 0.65, "threshold_low": 0.55}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
