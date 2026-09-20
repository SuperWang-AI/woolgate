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


# ══════════════════════════════════════════════════════════════
# 插件系统 v2：UI 扩展点 + 配置扩展点
# ══════════════════════════════════════════════════════════════

# ── 预设组件挂载点 ──
UI_HOOK_DASHBOARD_WIDGETS = "dashboard.widgets"
UI_HOOK_ACCOUNT_CARD_FOOTER = "account.card.footer"
UI_HOOK_LOG_DETAIL_EXTRA = "log.detail.extra"
UI_HOOK_CONFIG_PAGE_EXTRA = "config.page.extra"

ALL_UI_HOOK_POINTS = [
    UI_HOOK_DASHBOARD_WIDGETS,
    UI_HOOK_ACCOUNT_CARD_FOOTER,
    UI_HOOK_LOG_DETAIL_EXTRA,
    UI_HOOK_CONFIG_PAGE_EXTRA,
]


# ── 1. 页面路由注入 ──
class PageRegistry:
    """页面注册表：route -> {title, render_func}"""

    def __init__(self):
        self._pages: Dict[str, dict] = {}

    def register(self, route: str, title: str, render_func: Any) -> None:
        if not route.startswith("/"):
            route = "/" + route
        self._pages[route] = {"title": title, "render": render_func}
        logger.info(f"[sdk] 插件页面注册: {route} ({title})")

    def get(self, route: str) -> Optional[dict]:
        if not route.startswith("/"):
            route = "/" + route
        return self._pages.get(route)

    def list(self) -> Dict[str, dict]:
        return dict(self._pages)


page_registry = PageRegistry()


def register_page(route: str, title: str, render_func: Any) -> None:
    """
    注册独立管理后台页面。

    Args:
        route: 页面路由路径（如 "/balance"，最终为 /admin/balance）
        title: 页面标题
        render_func: 页面渲染函数（接收 request 参数，在 NiceGUI 页面上下文中执行）
    """
    page_registry.register(route, title, render_func)


# ── 2. 导航菜单扩展 ──
class NavRegistry:
    """导航菜单注册表：[{label, route, icon}]"""

    def __init__(self):
        self._items: list = []

    def register(self, label: str, route: str, icon: Optional[str] = None) -> None:
        if not route.startswith("/"):
            route = "/" + route
        self._items.append({"label": label, "route": route, "icon": icon})
        logger.info(f"[sdk] 插件导航注册: {label} -> {route}")

    def list(self) -> list:
        return list(self._items)


nav_registry = NavRegistry()


def register_nav_item(label: str, route: str, icon: Optional[str] = None) -> None:
    """
    注册导航菜单项。

    Args:
        label: 菜单显示名称
        route: 点击跳转的路由（如 "/balance"）
        icon: 可选图标（emoji 或字符）
    """
    nav_registry.register(label, route, icon)


# ── 3. 组件挂载点 ──
class ComponentRegistry:
    """组件挂载点注册表：hook_point -> [{render_func, priority}]"""

    def __init__(self):
        self._components: Dict[str, list] = {}

    def register(self, hook_point: str, render_func: Any, priority: int = 100) -> None:
        if hook_point not in ALL_UI_HOOK_POINTS:
            logger.warning(f"[sdk] 组件挂载点 {hook_point} 不在预设列表中，仍会注册（自定义挂载点需主程序支持）")
        self._components.setdefault(hook_point, []).append({
            "render": render_func,
            "priority": priority,
        })
        logger.info(f"[sdk] 插件组件注册: {hook_point} (priority={priority})")

    def get_sorted(self, hook_point: str) -> list:
        """按优先级排序（数字越小越靠前）"""
        comps = self._components.get(hook_point, [])
        return sorted(comps, key=lambda x: x["priority"])

    def list_all(self) -> Dict[str, list]:
        return dict(self._components)


component_registry = ComponentRegistry()


def register_component(hook_point: str, render_func: Any, priority: int = 100) -> None:
    """
    注册组件到指定挂载点。

    Args:
        hook_point: 挂载点 ID（预设：dashboard.widgets / account.card.footer / log.detail.extra / config.page.extra）
        render_func: 组件渲染函数（在 NiceGUI 上下文中执行，可接收上下文参数）
        priority: 优先级，数字越小越靠前（默认100）
    """
    component_registry.register(hook_point, render_func, priority)


# ── 4. 配置界面注入 ──
class ConfigRegistry:
    """配置注册表：plugin_name -> {schema, default, on_save}"""

    def __init__(self):
        self._configs: Dict[str, dict] = {}

    def register(self, plugin_name: str, schema: dict, default: dict,
                 on_save: Optional[Any] = None) -> None:
        self._configs[plugin_name] = {
            "schema": schema,
            "default": default,
            "on_save": on_save,
        }
        logger.info(f"[sdk] 插件配置注册: {plugin_name} ({len(schema)} 个字段)")

    def get(self, plugin_name: str) -> Optional[dict]:
        return self._configs.get(plugin_name)

    def list(self) -> Dict[str, dict]:
        return dict(self._configs)


config_registry = ConfigRegistry()


def register_config(schema: dict, default: dict, on_save: Optional[Any] = None) -> None:
    """
    注册插件配置表单（在统一插件配置页面展示和保存）。

    Args:
        schema: 配置表单定义，格式 {key: {type, label, default, help, options}}
            type 支持: string / number / boolean / select / textarea
        default: 默认值字典
        on_save: 保存时的回调函数（接收 config dict 参数），可选
    """
    # 自动从调用栈获取插件模块名
    import inspect
    frame = inspect.currentframe()
    caller_module = "unknown"
    try:
        if frame and frame.f_back:
            caller_module = frame.f_back.f_globals.get("__name__", "unknown")
    finally:
        del frame
    config_registry.register(caller_module, schema, default, on_save)


# ── 5. 插件配置读写函数 ──
async def get_plugin_config(plugin_name: str) -> dict:
    """
    获取插件配置（合并默认值 + 数据库存储值 + 环境变量覆盖）。

    优先级：环境变量 > 数据库配置 > 默认值
    环境变量格式：WOOLGATE_PLUGIN_{PLUGIN_NAME}_{KEY}（大写，点号转下划线）

    Args:
        plugin_name: 插件模块名（如 "plugins.balance_monitor"）

    Returns:
        配置字典
    """
    import os

    # 1. 从注册的 schema 获取默认值
    config_info = config_registry.get(plugin_name)
    result = {}
    if config_info:
        result.update(config_info.get("default", {}))

    # 2. 从数据库读取
    try:
        from app.models import AsyncSessionLocal
        from app.models.database import SystemConfig
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result_db = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
            config = result_db.scalar_one_or_none()
            if config and config.plugin_configs:
                plugin_cfg = config.plugin_configs.get(plugin_name, {})
                result.update(plugin_cfg)
    except Exception as e:
        logger.warning(f"[sdk] 读取插件配置失败（使用默认值）: {plugin_name}: {e}")

    # 3. 环境变量覆盖
    env_prefix = f"WOOLGATE_PLUGIN_{plugin_name.upper().replace('.', '_').replace('-', '_')}_"
    for key in list(result.keys()):
        env_key = f"{env_prefix}{key.upper().replace('.', '_').replace('-', '_')}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            # 类型转换
            original = result[key]
            if isinstance(original, bool):
                result[key] = env_val.lower() in ("true", "1", "yes", "on")
            elif isinstance(original, int):
                try:
                    result[key] = int(env_val)
                except ValueError:
                    pass
            elif isinstance(original, float):
                try:
                    result[key] = float(env_val)
                except ValueError:
                    pass
            else:
                result[key] = env_val

    return result


async def set_plugin_config(plugin_name: str, config: dict) -> None:
    """
    保存插件配置到数据库。

    Args:
        plugin_name: 插件模块名
        config: 配置字典（会合并到现有配置中）
    """
    try:
        from app.models import AsyncSessionLocal
        from app.models.database import SystemConfig
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
            sys_config = result.scalar_one_or_none()
            if not sys_config:
                sys_config = SystemConfig(id=1)
                session.add(sys_config)
                await session.flush()

            if not sys_config.plugin_configs:
                sys_config.plugin_configs = {}

            # 合并配置
            if plugin_name not in sys_config.plugin_configs:
                sys_config.plugin_configs[plugin_name] = {}
            sys_config.plugin_configs[plugin_name].update(config)

            await session.commit()

            # 触发 on_save 回调
            config_info = config_registry.get(plugin_name)
            if config_info and config_info.get("on_save"):
                try:
                    callback = config_info["on_save"]
                    if callable(callback):
                        merged = await get_plugin_config(plugin_name)
                        callback(merged)
                except Exception as e:
                    logger.error(f"[sdk] 插件配置 on_save 回调异常: {plugin_name}: {e}")

            logger.info(f"[sdk] 插件配置已保存: {plugin_name}")
    except Exception as e:
        logger.error(f"[sdk] 保存插件配置失败: {plugin_name}: {e}", exc_info=True)
        raise
