"""
系统配置页面
"""
from __future__ import annotations
from nicegui import ui
from .base import BasePage
from app.admin.services import get_system_config, save_system_config
from app.extensions.sdk import component_registry, UI_HOOK_CONFIG_PAGE_EXTRA


class ConfigPage(BasePage):
    """系统配置"""

    async def load(self):
        """加载系统配置"""
        self.config = await get_system_config()

    async def render(self):
        """渲染系统配置页面"""
        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            ui.label('全局系统配置').classes('text-3xl font-bold text-gray-800')
            ui.label('所有配置保存后立即生效，无需重启服务').classes('text-sm text-gray-500 -mt-2')

            # 对外模型名（网关统一入口，单一数据源）
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('对外模型名（网关统一入口）').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('客户端（Dify/OpenClaw 等）配置模型时统一填这个名字，网关内部智能路由自动映射真实模型').classes('text-xs text-gray-500 mb-3')
                entry_name = ui.input(
                    '对外模型名',
                    value=getattr(self.config, 'virtual_model_name', 'woolgate') or 'woolgate',
                ).classes('w-full max-w-md').props('placeholder=woolgate')
                ui.label('修改后，首页 Dify 配置示例、/v1/models 模型列表、路由判断将同步生效').classes('text-xs text-amber-600')
                with ui.expansion('为什么有这个字段？入口名 vs 真实模型名', icon='help').classes('w-full mt-1'):
                    ui.label('· 入口名（如 woolgate）：客户端只需填一个名字，网关智能路由自动选最合适/最省钱的模型，客户端无需了解后端模型结构').classes('text-xs text-gray-600 mb-1')
                    ui.label('· 真实模型名（如 deepseek-chat）：点名直走该模型，仍享受多账号比价、故障切换、统一账单').classes('text-xs text-gray-600 mb-1')
                    ui.label('· 两者都不是：返回明确报错，避免配置错误被静默掩盖').classes('text-xs text-gray-600')

            # 额度耗尽策略
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('额度耗尽策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('账号免费额度用尽后的处理方式').classes('text-xs text-gray-500 mb-3')
                quota_strategy = ui.select(
                    {
                        'auto_switch_next': '自动切换到下一个账号',
                        'return_warn_error': '返回错误并提醒',
                        'allow_pay_quota': '允许扣费继续使用',
                    },
                    label='策略',
                    value=self.config.quota_exhaust_strategy,
                ).classes('w-full max-w-md')

            # 重试与日志
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('重试与日志').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('请求失败重试、故障冷却与日志保留参数').classes('text-xs text-gray-500 mb-3')
                with ui.grid(columns=3).classes('w-full gap-x-8 gap-y-4'):
                    with ui.column().classes('gap-1'):
                        max_retry = ui.number('最大重试次数', value=self.config.max_retry_count, min=0, max=10).classes('w-full')
                        ui.label('请求失败后最多重试几次').classes('text-xs text-gray-400')
                    with ui.column().classes('gap-1'):
                        cool_down = ui.number('故障冷却（秒）', value=self.config.cool_down_seconds, min=0).classes('w-full')
                        ui.label('失败后暂停使用该账号的时长').classes('text-xs text-gray-400')
                    with ui.column().classes('gap-1'):
                        log_retention = ui.number('日志保留（天）', value=self.config.log_retention_days, min=1).classes('w-full')
                        ui.label('请求日志自动清理周期').classes('text-xs text-gray-400')

            # 保存按钮
            async def save():
                config_data = {
                    'quota_exhaust_strategy': quota_strategy.value,
                    'max_retry_count': int(max_retry.value),
                    'cool_down_seconds': int(cool_down.value),
                    'log_retention_days': int(log_retention.value),
                    'virtual_model_name': (entry_name.value or 'woolgate').strip(),
                }
                success = await save_system_config(config_data)
                if success:
                    ui.notify('配置已保存', type='positive')
                else:
                    ui.notify('保存失败', type='negative')

            with ui.row().classes('w-full justify-end'):
                ui.button('保存配置', on_click=save).props('color=primary size=lg')

            # 企业版入口
            with ui.card().classes('w-full shadow-lg p-4 border-t-4 border-indigo-500'):
                ui.label('企业版（开源版之外的能力）').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('开源版面向个人与自用场景；团队与组织需要以下能力时，可升级企业版获得支持与部署保障').classes('text-xs text-gray-500 mb-3')
                with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-2'):
                    ui.label('· 多租户：团队/项目隔离，独立 Key 与权限').classes('text-xs text-gray-600')
                    ui.label('· 配额预算：按租户统计用量，超限自动停用').classes('text-xs text-gray-600')
                    ui.label('· 审计与账单：按租户隔离日志与费用明细').classes('text-xs text-gray-600')
                    ui.label('· 本地智能省钱模式：本地判题/直答，数据不出域').classes('text-xs text-gray-600')
                ui.label('企业版计划即将推出，如需提前接入请通过项目主页联系作者').classes('text-xs text-amber-600 mt-2')

            # ── 插件挂载点：config.page.extra ──
            config_extras = component_registry.get_sorted(UI_HOOK_CONFIG_PAGE_EXTRA)
            if config_extras:
                ui.separator().classes('my-4')
                ui.label('🔌 插件扩展配置').classes('text-2xl font-bold text-gray-800')
                for extra in config_extras:
                    try:
                        render_fn = extra['render']
                        if callable(render_fn):
                            result = render_fn()
                            if hasattr(result, '__await__'):
                                await result
                    except Exception as e:
                        with ui.card().classes('w-full bg-red-50 border-l-4 border-red-500 p-3'):
                            ui.label(f'插件组件异常: {e}').classes('text-red-700 text-sm')
