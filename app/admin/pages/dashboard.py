"""
首页仪表盘页面
"""
from __future__ import annotations
import json
from nicegui import ui
from starlette.requests import Request
from .base import BasePage


class DashboardPage(BasePage):
    """首页仪表盘"""

    def __init__(self, db=None, config=None, request: Request = None):
        super().__init__(db, config)
        self.request = request

    async def render(self):
        """渲染首页仪表盘（由 admin.py 中的 _needs_onboard / _render_dashboard 提供具体实现）"""
        # 具体的引导和仪表盘渲染逻辑仍在 admin.py 中，这里只是一个占位
        # 实际的渲染由 admin.py 中的 home_view 直接调用
        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            ui.label('首页加载中...').classes('text-gray-500')
