"""
插件加载器（A3）——v0.6.0

启动时扫描 WOOLGATE_PLUGINS 环境变量（逗号分隔模块路径）逐个 import。
插件 import 失败：记日志、跳过，不影响应用启动（契约 03 第 5 节）。
"""
import importlib
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ENV_PLUGINS = "WOOLGATE_PLUGINS"

# ── 全局插件注册表（P2 插件管理页用）──
_PLUGIN_REGISTRY: Dict[str, dict] = {}


def register_plugin(module_name: str, status: str, error: Optional[str] = None, 
                    friendly_name: Optional[str] = None, version: Optional[str] = None,
                    author: Optional[str] = None, description: Optional[str] = None,
                    tags: Optional[List[str]] = None) -> None:
    """注册插件元信息到全局注册表"""
    # 如果没有指定友好名称，使用模块路径的最后一部分
    if not friendly_name:
        friendly_name = module_name.split('.')[-1] if '.' in module_name else module_name
    _PLUGIN_REGISTRY[module_name] = {
        "module": module_name,
        "name": friendly_name,
        "version": version or "unknown",
        "author": author or "unknown",
        "description": description or "",
        "tags": tags or [],
        "status": status,  # loaded / failed
        "error": error,
    }


def get_plugin_registry() -> Dict[str, dict]:
    """获取全局插件注册表（副本）"""
    return dict(_PLUGIN_REGISTRY)


def _match_plugin(func_module: str) -> Optional[str]:
    """根据函数模块名精确匹配所属插件（按模块路径层级分割，避免前缀误匹配）"""
    if not func_module:
        return None
    func_parts = func_module.split('.')
    for mod_name, info in _PLUGIN_REGISTRY.items():
        mod_parts = mod_name.split('.')
        # 精确匹配：函数模块以插件模块为完整前缀（按层级）
        if len(func_parts) >= len(mod_parts) and func_parts[:len(mod_parts)] == mod_parts:
            return info['name']
    return None


def get_plugin_stats() -> dict:
    """获取插件统计信息（钩子数、SPI 数、UI扩展点数）"""
    from app.extensions.hooks import hook_registry
    from app.extensions.sdk import spi_registry, page_registry, nav_registry, component_registry, config_registry

    # 使用公共 snapshot 方法，不直接访问私有属性
    hook_snapshot = hook_registry.snapshot_all()
    spi_snapshot = spi_registry.snapshot_all()

    # 统计钩子数
    hook_count = sum(len(hooks) for hooks in hook_snapshot.values())
    hook_events = hook_registry.events()

    # 统计 SPI 数
    spi_count = sum(len(impls) for impls in spi_snapshot.values())
    spi_types = spi_registry.types()

    # 统计 UI 扩展点
    page_count = len(page_registry.list())
    nav_count = len(nav_registry.list())
    component_count = sum(len(v) for v in component_registry.list_all().values())
    config_count = len(config_registry.list())

    # 收集钩子详情（事件 -> [{plugin, function, priority}]）
    hook_details: Dict[str, List[dict]] = {}
    for event, hooks in hook_snapshot.items():
        hook_details[event] = []
        for priority, order, func in hooks:
            func_module = getattr(func, '__module__', '')
            plugin_name = _match_plugin(func_module)
            hook_details[event].append({
                'plugin': plugin_name or func_module or 'core',
                'function': getattr(func, '__name__', str(func)),
                'priority': priority,
            })

    # 收集 SPI 详情（类型 -> [{plugin, name}]）
    spi_details: Dict[str, List[dict]] = {}
    for spi_type, impls in spi_snapshot.items():
        spi_details[spi_type] = []
        for name, impl in impls.items():
            impl_module = getattr(impl, '__module__', '')
            plugin_name = _match_plugin(impl_module)
            spi_details[spi_type].append({
                'plugin': plugin_name or impl_module or 'core',
                'name': name,
            })

    return {
        "total_plugins": len(_PLUGIN_REGISTRY),
        "loaded_plugins": sum(1 for p in _PLUGIN_REGISTRY.values() if p["status"] == "loaded"),
        "failed_plugins": sum(1 for p in _PLUGIN_REGISTRY.values() if p["status"] == "failed"),
        "hook_count": hook_count,
        "hook_events": hook_events,
        "hook_details": hook_details,
        "spi_count": spi_count,
        "spi_types": spi_types,
        "spi_details": spi_details,
        "ui_pages": page_count,
        "ui_nav_items": nav_count,
        "ui_components": component_count,
        "plugin_configs": config_count,
        "plugins": dict(_PLUGIN_REGISTRY),
    }


def unload_plugin(module_name: str) -> bool:
    """
    从注册表移除插件元信息（预留接口；不做 import 回滚，仅清理注册状态）。
    运行时完全卸载需要重启进程，Python 不支持可靠的模块热卸载。
    Returns:
        True 如果插件存在并已移除，False 如果不存在
    """
    if module_name in _PLUGIN_REGISTRY:
        del _PLUGIN_REGISTRY[module_name]
        logger.info(f"[extensions] 插件已从注册表移除: {module_name}")
        return True
    logger.warning(f"[extensions] 卸载失败，插件未注册: {module_name}")
    return False


def load_plugins() -> List[str]:
    """
    加载所有配置的插件模块。

    Returns:
        成功加载的插件模块名列表
    """
    raw = os.environ.get(ENV_PLUGINS, "").strip()
    if not raw:
        return []

    loaded: List[str] = []
    for module_name in [m.strip() for m in raw.split(",") if m.strip()]:
        try:
            mod = importlib.import_module(module_name)
            loaded.append(module_name)
            # 读取插件元信息
            friendly_name = getattr(mod, 'PLUGIN_NAME', None)
            version = getattr(mod, 'PLUGIN_VERSION', None)
            author = getattr(mod, 'PLUGIN_AUTHOR', None)
            description = getattr(mod, 'PLUGIN_DESCRIPTION', None)
            tags = getattr(mod, 'PLUGIN_TAGS', None)
            register_plugin(module_name, "loaded", 
                           friendly_name=friendly_name, version=version,
                           author=author, description=description, tags=tags)
            logger.info(f"[extensions] 插件加载成功: {module_name} (名称: {friendly_name or module_name}, 版本: {version or 'unknown'})")
        except Exception as e:
            register_plugin(module_name, "failed", str(e))
            logger.error(f"[extensions] 插件加载失败（已跳过，不影响启动）: {module_name}: {e}",
                         exc_info=True)
    return loaded
