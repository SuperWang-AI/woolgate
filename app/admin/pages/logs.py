"""
请求日志页面
"""
from __future__ import annotations
from nicegui import ui
from .base import BasePage
from app.admin.services import get_log_stats, get_recent_logs, get_error_breakdown
from app.admin.utils import format_local_time
from app.extensions.sdk import component_registry, UI_HOOK_LOG_DETAIL_EXTRA


class LogsPage(BasePage):
    """请求日志"""

    async def load(self):
        """加载日志数据"""
        self.stats = await get_log_stats()
        self.logs = await get_recent_logs(50)
        self.error_bd = await get_error_breakdown(hours=24)

    async def render(self):
        """渲染请求日志页面"""
        @ui.refreshable
        async def logs_content():
            await self.load()

            with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
                with ui.row().classes('items-center justify-between w-full'):
                    ui.label('请求日志').classes('text-3xl font-bold text-gray-800')
                    ui.button('刷新', on_click=logs_content.refresh).props('outline color=primary')

                def stat_card(icon, icon_color, title, value, sub=None):
                    with ui.card().classes('flex-1').style('height:120px'):
                        with ui.column().classes('w-full items-center gap-1 justify-center').style('height:100%'):
                            ui.label((icon + ' ') if icon else title).classes('text-sm text-gray-600')
                            ui.label(value).classes('text-3xl font-bold').style('min-height:36px; display:flex; align-items:center; justify-content:center;')
                            if sub:
                                lines = sub if isinstance(sub, (list, tuple)) else [sub]
                                for line in lines:
                                    ui.label(line).classes('text-xs text-gray-500 text-center').style('line-height:1.4')

                total_count = self.stats['total_count']
                success_count = self.stats['success_count']
                failed_count = self.stats['failed_count']
                total_prompt = self.stats['total_prompt']
                total_completion = self.stats['total_completion']

                with ui.row().classes('w-full gap-3'):
                    stat_card('📊', 'text-blue-600', '总请求数', str(total_count))
                    stat_card('✅', 'text-green-600', '成功', str(success_count))
                    stat_card('❌', 'text-red-600', '失败', str(failed_count))
                    stat_card('🐑', 'text-orange-600', '累计Token',
                              f"{total_prompt + total_completion:,}",
                              [f'输入 {total_prompt:,}', f'输出 {total_completion:,}'])

                # 错误聚合（最近24h）
                if self.error_bd['total_failed'] > 0:
                    with ui.card().classes('w-full bg-red-50 border border-red-200').style('border-left:4px solid #ef4444'):
                        with ui.column().classes('w-full gap-2 p-1'):
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('bug_report').classes('text-red-600')
                                ui.label(f"⚠️ 错误聚合 · 最近 {self.error_bd['window_hours']}h").classes('text-md font-bold text-red-700')
                                ui.label(f"共 {self.error_bd['total_failed']} 次失败").classes('text-sm text-red-600 ml-2')
                            # 按厂商分布
                            with ui.row().classes('w-full gap-2 flex-wrap'):
                                for v in self.error_bd['by_vendor']:
                                    with ui.badge(f"{v['vendor']}: {v['count']}").classes('text-white').style('background:#dc2626'):
                                        pass
                            # 最近错误样本
                            if self.error_bd['samples']:
                                ui.label('最近错误样本：').classes('text-xs text-gray-600 mt-1')
                                for smp in self.error_bd['samples'][:5]:
                                    with ui.row().classes('w-full items-start gap-2 text-xs'):
                                        ui.label(smp['vendor']).classes('text-red-700 font-mono whitespace-nowrap')
                                        ui.label(smp['error']).classes('text-gray-700 break-all')

                # 日志列表
                if self.logs:
                    for log in self.logs:
                        # 提取数据
                        log_vendor = log.vendor or '未知'
                        log_model = log.model_name or '未知'
                        log_status = log.status
                        log_created = format_local_time(log.created_at)
                        log_prompt_tokens = log.prompt_tokens or 0
                        log_completion_tokens = log.completion_tokens or 0
                        log_total_tokens = log.total_tokens or 0
                        log_response_time = log.response_time_ms or 0
                        log_error = log.error_message
                        log_account_id = log.account_id
                        log_implicit_signal = log.implicit_signal
                        log_user_feedback = log.user_feedback

                        # 状态颜色
                        if log_status == 'success':
                            status_color = 'positive'
                            status_icon = 'check_circle'
                        else:
                            status_color = 'negative'
                            status_icon = 'error'

                        # A3: 隐式信号/显式反馈徽标映射
                        signal_badges = {
                            'switch_retry': ('切换重试', 'warning'),
                            'stream_interrupted': ('输出中断', 'negative'),
                            'followup': ('继续追问', 'positive'),
                        }
                        feedback_badges = {
                            'up': ('👍', 'positive'),
                            'down': ('👎', 'negative'),
                            'neutral': ('➖', 'info'),
                        }

                        with ui.card().classes('w-full shadow-sm hover:shadow-md transition-shadow'):
                            with ui.row().classes('w-full items-start justify-between gap-4'):
                                # 左侧信息
                                with ui.column().classes('flex-1 gap-2'):
                                    # 标题行
                                    with ui.row().classes('items-center gap-2 flex-wrap'):
                                        ui.icon(status_icon, size='sm').classes(f'text-{status_color}')
                                        ui.label(f'账号 {log_account_id}').classes('font-bold text-gray-800')
                                        ui.label(log_vendor).classes('text-sm bg-blue-100 text-blue-700 px-2 py-1 rounded')
                                        ui.badge(log_model, color='purple')
                                        ui.label(log_created).classes('text-xs text-gray-500')
                                        # A3: 隐式信号 + 显式反馈
                                        if log_implicit_signal in signal_badges:
                                            label, color = signal_badges[log_implicit_signal]
                                            ui.badge(label, color=color).props('outline')
                                        if log_user_feedback in feedback_badges:
                                            icon, color = feedback_badges[log_user_feedback]
                                            ui.badge(icon, color=color).props('outline')

                                    # Token 统计
                                    with ui.row().classes('items-center gap-4 text-sm'):
                                        ui.label(f'输入: {log_prompt_tokens:,}').classes('text-gray-600')
                                        ui.label(f'输出: {log_completion_tokens:,}').classes('text-gray-600')
                                        ui.label(f'总计: {log_total_tokens:,}').classes('text-gray-600 font-bold')
                                        ui.label(f'{log_response_time}ms').classes('text-gray-600')

                                    # C5: 成本/决策/分类引擎明细
                                    log_est_cost = getattr(log, 'estimated_cost', 0) or 0
                                    log_act_cost = getattr(log, 'actual_cost', 0) or 0
                                    log_router_dec = getattr(log, 'router_decision', None)
                                    log_selector_dec = getattr(log, 'selector_decision', None)
                                    log_classify_eng = getattr(log, 'classify_engine', None)
                                    log_degraded = getattr(log, 'degraded', False)
                                    log_degrade_reason = getattr(log, 'degrade_reason', None)

                                    has_c5_detail = any([
                                        log_est_cost > 0, log_act_cost > 0,
                                        log_router_dec, log_selector_dec,
                                        log_classify_eng, log_degraded,
                                    ])
                                    if has_c5_detail:
                                        ui.separator().classes('my-1')
                                        with ui.column().classes('gap-1'):
                                            with ui.row().classes('items-center gap-4 text-sm'):
                                                ui.label('💰 成本').classes('text-gray-500 font-medium')
                                                ui.label(f'估算: ¥{log_est_cost:.6f}').classes('text-gray-600')
                                                ui.label(f'实际: ¥{log_act_cost:.6f}').classes('text-gray-600 font-bold')
                                            with ui.row().classes('items-center gap-2 text-xs flex-wrap'):
                                                if log_classify_eng:
                                                    eng_label = {'vector': '向量分类', 'llm': 'LLM分类', 'off': '未分类'}.get(log_classify_eng, log_classify_eng)
                                                    ui.badge(f'分类: {eng_label}', color='info').props('outline')
                                                if log_router_dec:
                                                    ui.badge(f'路由: {log_router_dec[:50]}', color='primary').props('outline')
                                                if log_selector_dec:
                                                    ui.badge(f'选号: {log_selector_dec[:50]}', color='secondary').props('outline')
                                                if log_degraded:
                                                    degrade_text = f'降级: {log_degrade_reason}' if log_degrade_reason else '已降级'
                                                    ui.badge(degrade_text[:60], color='warning').props('outline')

                                    # 错误信息
                                    if log_error:
                                        ui.separator().classes('my-1')
                                        with ui.row().classes('items-start gap-2'):
                                            ui.icon('warning', size='sm').classes('text-red-500')
                                            ui.label(str(log_error)).classes('text-sm text-red-600 flex-1')

                                    # ── 插件挂载点：log.detail.extra ──
                                    log_detail_components = component_registry.get_sorted(UI_HOOK_LOG_DETAIL_EXTRA)
                                    if log_detail_components:
                                        ui.separator().classes('my-1')
                                        for comp in log_detail_components:
                                            try:
                                                render_fn = comp['render']
                                                if callable(render_fn):
                                                    result = render_fn(log)
                                                    if hasattr(result, '__await__'):
                                                        await result
                                            except Exception as e:
                                                with ui.row().classes('items-center gap-2 px-2 py-1 bg-red-50 rounded'):
                                                    ui.icon('error', size='sm').classes('text-red-500')
                                                    ui.label(f'插件组件异常: {e}').classes('text-xs text-red-600')
                else:
                    with ui.card().classes('w-full text-center p-12'):
                        ui.icon('inbox', size='4rem').classes('text-gray-400')
                        ui.label('暂无日志记录').classes('text-xl text-gray-500 mt-4')

        await logs_content()
