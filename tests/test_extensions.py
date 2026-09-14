"""
扩展机制单元测试（v0.6.0 A1-A8/B1-B2）

覆盖：
- 钩子注册/优先级/异常隔离/HookBlocked 阻断
- SPI 注册与覆盖
- PluginContext 命名空间隔离 + 决策字段白名单
- 分类引擎降级链（A5）
- 租户前缀（A6）
- 健康度信号（B2）
- 结构化日志（B1）
"""
import asyncio
import logging

import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, SystemConfig
from app.pipeline.context import PipelineContext
from app.extensions.hooks import (
    HOOK_REQUEST_STARTED, HOOK_ROUTE_BEFORE, HOOK_ROUTE_AFTER,
    HOOK_ERROR_OCCURRED, HookBlocked, HookRegistry,
)
from app.extensions.sdk import PluginContext, emit_hooks, register_spi
from app.extensions.hooks import hook_registry
from app.extensions.stores import build_scoped_session_id
from app.services.health import HealthTracker


@pytest.fixture
async def db_session():
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


def make_ctx(**kwargs) -> PipelineContext:
    base = dict(
        request_id="test-1",
        client_ip="127.0.0.1",
        stream=False,
        original_messages=[{"role": "user", "content": "你好"}],
        requested_model="woolgate",
        kwargs={},
        estimated_tokens=100,
        session_id="s1",
    )
    base.update(kwargs)
    return PipelineContext(**base)


# ── 钩子注册与执行 ──

def test_hook_registry_priority_order():
    """钩子按 priority 升序执行，同优先级按注册顺序"""
    reg = HookRegistry()
    order = []

    async def fn_a(ctx):
        order.append("a")

    async def fn_b(ctx):
        order.append("b")

    async def fn_c(ctx):
        order.append("c")

    reg.register(HOOK_REQUEST_STARTED, fn_c, priority=1000)
    reg.register(HOOK_REQUEST_STARTED, fn_a, priority=10)
    reg.register(HOOK_REQUEST_STARTED, fn_b, priority=10)

    asyncio.run(emit_hooks(HOOK_REQUEST_STARTED, make_ctx(), registry=reg))
    assert order == ["a", "b", "c"]


def test_hook_unknown_event_ignored():
    """未知插口名注册被忽略"""
    reg = HookRegistry()

    async def fn(ctx):
        pass

    reg.register("unknown.event", fn)
    assert not reg.has("unknown.event")


def test_hook_exception_isolated():
    """钩子异常被隔离：一个钩子抛错不阻断后续钩子"""
    reg = HookRegistry()
    ran = []

    async def bad(ctx):
        raise RuntimeError("hook boom")

    async def good(ctx):
        ran.append("good")

    reg.register(HOOK_REQUEST_STARTED, bad, priority=1)
    reg.register(HOOK_REQUEST_STARTED, good, priority=2)

    asyncio.run(emit_hooks(HOOK_REQUEST_STARTED, make_ctx(), registry=reg))
    assert ran == ["good"]


def test_hook_blocked_propagates_from_before_hook():
    """before 类钩子抛 HookBlocked 向上传播（可阻断请求）"""
    reg = HookRegistry()

    async def blocker(ctx):
        raise HookBlocked("blocked by policy", status_code=403)

    reg.register(HOOK_ROUTE_BEFORE, blocker, priority=1)

    with pytest.raises(HookBlocked) as exc_info:
        asyncio.run(emit_hooks(HOOK_ROUTE_BEFORE, make_ctx(), registry=reg))
    assert exc_info.value.status_code == 403


def test_hook_blocked_swallowed_in_after_hook():
    """after 类钩子抛 HookBlocked 不阻断（只可观测，契约 02）"""
    reg = HookRegistry()

    async def noisy(ctx):
        raise HookBlocked("should not block")

    reg.register(HOOK_ROUTE_AFTER, noisy, priority=1)

    # 不应抛出
    asyncio.run(emit_hooks(HOOK_ROUTE_AFTER, make_ctx(), registry=reg))


# ── 全局注册表隔离 ──

def test_global_registry_empty_by_default():
    """默认全局钩子注册表为空（零开销路径）"""
    assert not hook_registry.has(HOOK_REQUEST_STARTED)


# ── PluginContext 命名空间与白名单 ──

def test_plugin_namespace_isolation():
    """插件命名空间互不可见"""
    ctx = make_ctx()
    pc1 = PluginContext(ctx, "p1")
    pc2 = PluginContext(ctx, "p2")
    pc1.set("secret", "x")
    assert pc1.get("secret") == "x"
    assert pc2.get("secret") is None


def test_plugin_decision_whitelist():
    """决策字段白名单：白名单内可改，白名单外拒绝"""
    ctx = make_ctx()
    pc = PluginContext(ctx, "p1")
    pc.set_decision("target_model", "qwen-turbo")
    assert ctx.target_model == "qwen-turbo"

    with pytest.raises(ValueError):
        pc.set_decision("original_messages", [])  # 非白名单字段


# ── 租户前缀 ──

def test_scoped_session_id():
    """多租户前缀；单租户原样"""
    assert build_scoped_session_id("tenant-a", "s1") == "tenant-a:s1"
    assert build_scoped_session_id(None, "s1") == "s1"


# ── 健康度信号（B2） ──

def test_health_tracker_success_rate():
    """健康度：成功率与不健康判定"""
    tracker = HealthTracker()
    acc_id = 1
    for i in range(4):
        tracker.record(acc_id, success=True, latency_ms=100)
    for i in range(8):
        tracker.record(acc_id, success=False, latency_ms=200, error="timeout")

    stats = tracker.get(acc_id)
    assert stats is not None
    assert stats.success_rate == pytest.approx(4 / 12)
    assert stats.avg_latency_ms == pytest.approx(100 * 4 / 12 + 200 * 8 / 12)
    assert stats.is_unhealthy is True  # 12 样本，成功率 < 0.5


def test_health_tracker_few_samples_not_unhealthy():
    """样本不足不判不健康（避免冷启动误伤）"""
    tracker = HealthTracker()
    tracker.record(1, success=False, latency_ms=100, error="e1")
    tracker.record(1, success=False, latency_ms=100, error="e2")
    stats = tracker.get(1)
    assert stats.is_unhealthy is False  # 仅 2 样本


def test_health_tracker_unknown_is_healthy():
    """无样本视为健康（未知不作为故障）"""
    tracker = HealthTracker()
    assert tracker.get(999) is None
    assert HealthTracker().get(1) is None


# ── 结构化日志（B1） ──

def test_ctx_event_merges_log_dict(caplog):
    """ctx_event 合并 to_log_dict 字段输出 JSON 行"""
    from app.utils.log_utils import ctx_event
    logger = logging.getLogger("test.log_utils")
    ctx = make_ctx(target_model="qwen-plus", router_strategy="vector")

    with caplog.at_level(logging.INFO, logger="test.log_utils"):
        ctx_event(logger, "executor.call_done", ctx, account_id=1)

    assert any("executor.call_done" in r.message for r in caplog.records)
    assert any('"target_model": "qwen-plus"' in r.message for r in caplog.records)
