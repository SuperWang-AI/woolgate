"""
插件 SDK（最小 SDK）——v0.6.0 组件化/插件化预留

提供四个能力：
1. register_hook：注册生命周期钩子（9 插口）
2. register_spi：注册 SPI 实现（classifier/selector/router/context/security/adapter/store）
3. get_plugin：运行时取回自己的命名空间视图
4. PluginContext：受限上下文视图（只读写自己的命名空间，核心字段只读/受限改写）

详见 docs/extensions/03-plugin-sdk.md。
"""
import logging
from typing import Any, Dict, Optional, Type, TYPE_CHECKING

from app.extensions.hooks import (
    HOOK_ERROR_OCCURRED,
    MUTABLE_HOOKS,
    HookBlocked,
    HookFn,
    HookRegistry,
    hook_registry,
)

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

# 决策字段白名单：after 类钩子可改写（其余核心字段只读，防止插件破坏管线）
_DECISION_FIELDS = {
    "target_model",
    "router_decision",
    "router_confidence",
    "selector_decision",
    "assembled_messages",
    "degraded",
    "degrade_reason",
    "actual_cost",
}


class PluginContext:
    """插件运行时上下文：底层 ctx 只读 + 本插件命名空间可写"""

    def __init__(self, ctx: "PipelineContext", plugin_name: str):
        self._ctx = ctx
        self._plugin_name = plugin_name
        if plugin_name not in ctx.extensions:
            ctx.extensions[plugin_name] = {}

    # ── 只读访问底层核心字段 ──
    @property
    def ctx(self) -> "PipelineContext":
        return self._ctx

    def get(self, key: str, default: Any = None) -> Any:
        return self._ctx.extensions.get(self._plugin_name, {}).get(key, default)

    def set(self, key: str, value: Any) -> None:
        """只写自己的命名空间"""
        self._ctx.extensions.setdefault(self._plugin_name, {})[key] = value

    def set_decision(self, field: str, value: Any) -> None:
        """after 类钩子改写决策字段（before 钩子调用将抛错，防止语义混乱）"""
        if field not in _DECISION_FIELDS:
            raise ValueError(
                f"字段 {field} 不在可改写白名单内；插件只能写自己的命名空间（ctx.set）"
            )
        setattr(self._ctx, field, value)

    # ── 元信息 ──
    @property
    def name(self) -> str:
        return self._plugin_name


def register_hook(event: str, priority: int = 1000):
    """装饰器：注册生命周期钩子。priority 越小越先执行。"""

    def decorator(fn: HookFn) -> HookFn:
        hook_registry.register(event, fn, priority=priority)
        logger.info(f"[sdk] 插件钩子注册: {getattr(fn, '__module__', '?')}.{fn.__name__} @ {event}")
        return fn

    return decorator


# ── SPI 注册表（可替换实现）──
class SPIRegistry:
    """SPI 注册表：spi_type -> {name: impl}；同名注册覆盖（后注册优先）"""

    def __init__(self):
        self._impls: Dict[str, Dict[str, Any]] = {}

    def register(self, spi_type: str, name: str, impl: Any) -> None:
        self._impls.setdefault(spi_type, {})[name] = impl
        logger.info(f"[sdk] SPI 注册: {spi_type}/{name}")

    def get(self, spi_type: str, name: str) -> Optional[Any]:
        return self._impls.get(spi_type, {}).get(name)

    def list(self, spi_type: str) -> Dict[str, Any]:
        return dict(self._impls.get(spi_type, {}))


spi_registry = SPIRegistry()


def register_spi(spi_type: str, name: str, impl: Any) -> None:
    """注册 SPI 实现（classifier/selector/router/context/security/adapter/store）"""
    spi_registry.register(spi_type, name, impl)


def get_plugin(name: str, ctx: "PipelineContext") -> PluginContext:
    """运行时取回插件命名空间视图"""
    return PluginContext(ctx, name)


async def emit_hooks(event: str, ctx: "PipelineContext", registry: Optional[HookRegistry] = None) -> None:
    """
    触发一个插口的所有钩子。

    - 无钩子注册：直接返回（零开销路径）；
    - before 类钩子抛 HookBlocked → 向上传播（由调用方决定拒绝请求）；
    - 其他钩子异常 → 记日志继续（异常隔离，契约 03 第 6 节）。
    """
    reg = registry or hook_registry
    hooks = reg.snapshot(event)
    if not hooks:
        return

    for fn in hooks:
        try:
            await fn(ctx)
        except Exception as e:
            if isinstance(e, HookBlocked) and event not in MUTABLE_HOOKS:
                # before 类钩子主动阻断 → 向上传播，调用方转 4xx
                raise
            logger.error(f"[hooks] 插口 {event} 钩子 {getattr(fn, '__name__', '?')} 异常（已隔离）: {e}",
                         exc_info=True)
