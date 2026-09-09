"""
A2 启动意图引导测试

覆盖：
1. SystemConfig 表包含 onboarded / onboard_profile 字段
2. 引导映射（纯函数 build_onboard_data）：
   - 个人省钱 + 通用对话 + 免费云端 → hybrid / free-first / passthrough
   - 团队企业 + 编程 + 付费 → hybrid / cost-first / summary（摘要配置就位）
   - 创意/数据场景 → window 上下文
   - 本地模型来源 → ollama_enabled=True
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

def test_personal_chat_free_profile():
    """个人省钱 + 通用对话 + 免费云端 → hybrid / free-first / passthrough"""
    data, profile = build_onboard_data({"way": "personal", "scene": "chat", "source": "free"})
    assert data["router_strategy"] == "hybrid"
    assert data["selector_strategy"] == "free-first"
    assert data["context_strategy"] == "passthrough"
    assert data["onboarded"] is True
    assert "ollama_enabled" not in data  # 非本地来源不强制写
    assert profile == "个人省钱·通用对话·免费云端"


def test_team_code_paid_profile():
    """团队企业 + 编程开发 + 付费账号 → hybrid / cost-first / summary（带摘要配置）"""
    data, profile = build_onboard_data({"way": "team", "scene": "code", "source": "paid"})
    assert data["router_strategy"] == "hybrid"
    assert data["selector_strategy"] == "cost-first"
    assert data["context_strategy"] == "summary"
    assert data["context_config_json"]["summary_model"] == "glm-4-flash"
    assert data["context_config_json"]["summary_trigger_turns"] == 20
    assert "ollama_enabled" not in data
    assert profile == "企业使用·编程开发·付费账号"


def test_local_source_enables_ollama():
    """本地模型来源 → ollama_enabled=True"""
    data, _ = build_onboard_data({"way": "personal", "scene": "creative", "source": "local"})
    assert data["ollama_enabled"] is True
    assert data["context_strategy"] == "window"
    assert data["context_config_json"] == {"window_turns": 10}


def test_data_scene_window():
    """数据分析场景 → window 上下文"""
    data, _ = build_onboard_data({"way": "personal", "scene": "data", "source": "free"})
    assert data["context_strategy"] == "window"


def test_router_config_has_hybrid_thresholds():
    """hybrid 路由配置带智能路由默认阈值（0.65/0.55）"""
    data, _ = build_onboard_data({"way": "personal", "scene": "chat", "source": "free"})
    assert data["router_config_json"] == {"threshold_high": 0.65, "threshold_low": 0.55}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
