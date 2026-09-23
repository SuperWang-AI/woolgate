"""
统计卡片组件
用于仪表盘等页面展示数字统计
"""
from __future__ import annotations
from nicegui import ui


def render_stat_card(icon: str, icon_color: str, title: str, value: str, sub=None):
    """
    渲染统计卡片
    
    Args:
        icon: 图标名称
        icon_color: 图标颜色（如 'blue-500'）
        title: 卡片标题
        value: 主数值
        sub: 副标题（可以是字符串或列表，每行一条）
    """
    with ui.card().classes('flex-1 stat-card shadow-lg').style('height:170px'):
        with ui.column().classes('w-full items-center gap-1 justify-center').style('height:100%'):
            ui.icon(icon, size='2.5rem').classes(f'text-{icon_color}')
            ui.label(title).classes('text-gray-500 text-sm')
            ui.label(value).classes('text-3xl font-bold').style('min-height:36px; display:flex; align-items:center; justify-content:center;')
            if sub:
                lines = sub if isinstance(sub, (list, tuple)) else [sub]
                for line in lines:
                    ui.label(line).classes('text-xs text-gray-500 text-center').style('line-height:1.4')
