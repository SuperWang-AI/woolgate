"""
导航栏组件
包含顶部导航、插件下拉菜单
"""
from __future__ import annotations
from nicegui import ui


def render_navigation(active_key: str = "home"):
    """
    渲染顶部导航栏
    
    Args:
        active_key: 当前激活的导航项
    """
    # TODO: 从 admin.py 迁移导航栏 UI
    with ui.header().classes('items-center justify-between'):
        ui.label("WoolGate")
        # TODO: 导航按钮和插件下拉菜单
