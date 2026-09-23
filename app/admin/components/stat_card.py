"""
统计卡片组件
用于仪表盘等页面展示数字统计
"""
from __future__ import annotations
from nicegui import ui


def render_stat_card(title: str, value: str, subtitle: str = "", color: str = "blue"):
    """
    渲染统计卡片
    
    Args:
        title: 卡片标题
        value: 主数值
        subtitle: 副标题
        color: 主题色
    """
    # TODO: 从 admin.py 迁移统计卡片 UI
    with ui.card().classes('w-full'):
        ui.label(title)
        ui.label(value)
        if subtitle:
            ui.label(subtitle)
