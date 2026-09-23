"""
管理后台工具函数
所有与业务无关的通用工具函数都放在这里
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from nicegui import ui


# SPA 导航全局状态
_tabs_ref = None
_plugin_active = None
_plugin_refresh = None
KEY_TO_PATH = {
    'home': '/',
    'wizard': '/wizard',
    'accounts': '/accounts',
    'config': '/config',
    'pipeline': '/pipeline',
    'logs': '/logs',
    'plugins': '/plugins',
}


def init_spa_state(tabs_ref, plugin_active=None, plugin_refresh=None):
    """初始化 SPA 导航状态（在 create_ui 中调用）"""
    global _tabs_ref, _plugin_active, _plugin_refresh
    _tabs_ref = tabs_ref
    _plugin_active = plugin_active
    _plugin_refresh = plugin_refresh


def set_plugin_active(active: str = None):
    """设置当前激活的插件"""
    global _plugin_active
    _plugin_active = active


def get_plugin_active() -> str:
    """获取当前激活的插件"""
    return _plugin_active


def set_plugin_refresh(refresh_func):
    """设置插件页面刷新函数"""
    global _plugin_refresh
    _plugin_refresh = refresh_func


def spa_navigate(key: str, active: str = None):
    """SPA内导航：切换tab value + 同步URL，不触发整页刷新"""
    global _plugin_active
    if _tabs_ref is not None:
        _tabs_ref.value = key
    # 同步URL（不刷新页面）
    if key == 'plugins' and active:
        ui.run_javascript(f"history.replaceState(null, '', '/admin/plugins?active={active}')")
        _plugin_active = active
        # 触发插件页面刷新（SPA内切换插件）
        if _plugin_refresh is not None:
            _plugin_refresh()
    else:
        path = KEY_TO_PATH.get(key, '/')
        ui.run_javascript(f"history.replaceState(null, '', '/admin{path}')")
        if key == 'plugins':
            # 切回插件管理页面：重置active并刷新
            _plugin_active = None
            if _plugin_refresh is not None:
                _plugin_refresh()
        else:
            _plugin_active = None
    # 关闭插件下拉菜单
    ui.run_javascript("var dd = document.getElementById('plugin-dropdown-menu'); if(dd) dd.classList.add('hidden');")


def format_local_time(dt: datetime | None) -> str:
    """将 UTC 时间格式化为本地时间字符串"""
    if not dt:
        return "-"
    # TODO: 从 admin.py 迁移
    return ""


def get_today_start_utc() -> datetime:
    """获取今天 00:00 的 UTC 时间"""
    # TODO: 从 admin.py 迁移
    return datetime.now(timezone.utc)


def vendor_icon_html(icon: str, cls: str = "w-8 h-8 rounded object-contain") -> str:
    """生成厂商图标的 HTML"""
    # TODO: 从 admin.py 迁移
    return ""
