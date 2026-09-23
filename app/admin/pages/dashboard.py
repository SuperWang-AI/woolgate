"""
首页仪表盘页面
"""
from __future__ import annotations
from typing import Optional
from nicegui import ui
from starlette.requests import Request
from .base import BasePage
from app.admin.services import get_stats
from app.admin.components.stat_card import render_stat_card
from app.extensions.sdk import component_registry, UI_HOOK_DASHBOARD_WIDGETS


class DashboardPage(BasePage):
    """首页仪表盘"""

    def __init__(self, db=None, config=None, request: Request = None):
        super().__init__(db, config)
        self.request = request

    async def _needs_onboard(self) -> bool:
        """判断是否需要启动引导"""
        from app.models import AsyncSessionLocal
        from app.models.database import SystemConfig, ModelAccount
        from sqlalchemy import select, func
        
        preview = bool(self.request and self.request.query_params.get('onboard') == '1')
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
            config = result.scalar_one_or_none()
            onboarded = bool(config and getattr(config, "onboarded", False))
            if onboarded:
                return False
            if not preview:
                cnt = (await session.execute(select(func.count(ModelAccount.id)))).scalar() or 0
                return cnt == 0
            return True

    async def _render_onboard(self, on_done):
        """启动引导面板（简化版占位）"""
        with ui.column().classes('w-full items-center p-6'):
            with ui.card().classes('w-full shadow-lg border-t-4 border-green-500 p-6').style('max-width:760px'):
                ui.label('🐑 WoolGate AI 聚合网关').classes('text-2xl font-bold text-gray-800')
                ui.label('启动引导功能开发中...').classes('text-sm text-gray-500 mt-1')
                ui.button('跳过引导', on_click=on_done).props('color=primary')

    async def _render_dashboard(self):
        """首页仪表盘（引导完成后显示）"""
        # 主内容区域
        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            # 欢迎标题
            ui.label('AI 羊毛聚合网关').classes('text-4xl font-bold text-gray-800')
            ui.label('智能调度多平台免费额度，自动切换账号').classes('text-lg text-gray-500 -mt-4')
            
            # 统计数据
            stats = await get_stats()
            
            ui.label('实时统计').classes('text-2xl font-bold text-gray-800 mt-4')
            
            with ui.row().classes('w-full gap-4'):
                # 总账号数
                render_stat_card('account_circle', 'blue-500', '总账号数',
                          f"{stats['total_accounts']}",
                          f"✅ 启用: {stats['enabled_accounts']}")
                # 今日请求
                render_stat_card('analytics', 'purple-500', '今日请求',
                          f"{stats['today_requests']}",
                          "次")
                # 今日 Token
                today_total_m = (stats['today_prompt_tokens'] + stats['today_completion_tokens']) / 1_000_000
                render_stat_card('savings', 'orange-500', '今日 Token',
                          f"{today_total_m:.4f}M",
                          [f"输入 {stats['today_prompt_tokens'] / 1_000_000:.4f}M",
                           f"输出 {stats['today_completion_tokens'] / 1_000_000:.4f}M"])
                # 累计 Token
                total_total_m = (stats['total_prompt_tokens'] + stats['total_completion_tokens']) / 1_000_000
                render_stat_card('trending_up', 'red-500', '累计 Token',
                          f"{total_total_m:.4f}M",
                          [f"输入 {stats['total_prompt_tokens'] / 1_000_000:.4f}M",
                           f"输出 {stats['total_completion_tokens'] / 1_000_000:.4f}M"])
            
            # ── 插件挂载点：dashboard.widgets ──
            dashboard_widgets = component_registry.get_sorted(UI_HOOK_DASHBOARD_WIDGETS)
            if dashboard_widgets:
                ui.label('插件扩展').classes('text-2xl font-bold text-gray-800 mt-4')
                with ui.row().classes('w-full gap-4 flex-wrap'):
                    for widget in dashboard_widgets:
                        try:
                            render_fn = widget['render']
                            if callable(render_fn):
                                result = render_fn()
                                if hasattr(result, '__await__'):
                                    await result
                        except Exception as e:
                            with ui.card().classes('flex-1 bg-red-50 border-l-4 border-red-500 p-3'):
                                ui.label(f'插件组件异常: {e}').classes('text-red-700 text-sm')

    async def render(self):
        """渲染首页仪表盘"""
        @ui.refreshable
        async def render():
            if await self._needs_onboard():
                await self._render_onboard(on_done=render.refresh)
            else:
                await self._render_dashboard()
        await render()
