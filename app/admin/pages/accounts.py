"""
账号管理页面
"""
from __future__ import annotations
from nicegui import ui
from .base import BasePage
from app.admin.services import get_accounts, get_account_models
from app.extensions.sdk import component_registry, UI_HOOK_ACCOUNT_CARD_FOOTER


class AccountsPage(BasePage):
    """账号管理"""

    async def load(self):
        """加载账号数据"""
        self.accounts = await get_accounts()
        self.account_models = await get_account_models()

    async def render(self):
        """渲染账号管理页面"""
        # 页面获得焦点时自动刷新（多标签页同步：向导修改后切回账号管理自动更新）
        ui.run_javascript("""
            (function() {
                let _lastFocus = Date.now();
                let _reloadTimer = null;
                document.addEventListener('visibilitychange', function() {
                    if (!document.hidden) {
                        if (Date.now() - _lastFocus > 3000) {
                            clearTimeout(_reloadTimer);
                            _reloadTimer = setTimeout(function() { location.reload(); }, 800);
                        }
                    } else {
                        _lastFocus = Date.now();
                        clearTimeout(_reloadTimer);
                    }
                });
            })();
        """)

        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):

            async def recompute_all_vectors():
                """重算所有模型能力向量（高级工具，后续挂入高级设置）"""
                try:
                    from app.models.database import AsyncSessionLocal
                    from app.services.model_catalog import ModelCatalogService
                    from app.services.embedding import EmbeddingService
                    from app.pipeline.config import PipelineConfig
                    async with AsyncSessionLocal() as session:
                        cfg = await PipelineConfig.load(session)
                        embed_svc = EmbeddingService(cfg.router_config, db=session)
                        svc = ModelCatalogService(session)
                        count = await svc.recompute_all_embeddings(embed_svc)
                    ui.notify(f'已重算 {count} 个模型能力向量', type='positive')
                    from app.admin.admin import spa_navigate
                    spa_navigate('accounts')
                except Exception as e:
                    ui.notify(f'重算失败: {e}', type='negative')

            with ui.row().classes('items-center justify-between w-full'):
                ui.label('账号模型管理').classes('text-3xl font-bold text-gray-800')
                with ui.row().classes('gap-2'):
                    from app.admin.admin import show_account_dialog
                    ui.button('新增账号', on_click=lambda: show_account_dialog()).props('color=primary size=lg')

            accounts = self.accounts
            account_models = self.account_models

            def mask_key(acc):
                """密钥脱敏：已配置显示首尾，未配置显示占位"""
                from app.admin.admin import encryption_service
                if not acc.api_key_encrypted:
                    return '未配置密钥'
                try:
                    plain = encryption_service.decrypt(acc.api_key_encrypted)
                except Exception:
                    return '密钥不可读'
                if not plain:
                    return '未配置密钥'
                if len(plain) <= 10:
                    return '******'
                return f'{plain[:6]}****{plain[-4:]}'

            # 厂商分组：别名归一，避免历史命名差异把同一厂商拆成多组
            from collections import defaultdict
            from app.services.free_tier_catalog import FREE_TIER_VENDORS, vendor_matches

            def _canon_vendor(name):
                for v in FREE_TIER_VENDORS:
                    if vendor_matches(name or '', v['id']):
                        return v['name']
                return name

            vendor_groups = defaultdict(list)
            for acc in accounts:
                vendor_groups[_canon_vendor(acc.vendor)].append(acc)

            if accounts:
                # 厂商组固定顺序：内置目录顺序 + 其余按名称（避免随启停状态漂移）
                _v_index = {v['name']: i for i, v in enumerate(FREE_TIER_VENDORS)}
                for vendor in sorted(vendor_groups.keys(), key=lambda v: (_v_index.get(v, 999), v)):
                    vendor_accounts = vendor_groups[vendor]
                    total_models = sum(len(account_models.get(a.id, [])) for a in vendor_accounts)

                    # 厂商分组卡片（可折叠）
                    with ui.card().classes('w-full shadow-md'):
                        with ui.row().classes('w-full items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-100 transition-colors wg-row-click') as v_header:
                            ui.icon('business', size='md').classes('text-purple-600')
                            ui.label(vendor).classes('text-lg font-bold text-gray-800')
                            ui.badge(f'{len(vendor_accounts)} 个账号', color='indigo')
                            ui.badge(f'{total_models} 个模型', color='purple')
                            v_icon = ui.icon('expand_more', size='md').classes('text-gray-400 ml-auto')

                        with ui.column().classes('w-full px-4 pb-4 gap-3') as v_area:
                            v_area.visible = False

                            for acc in vendor_accounts:
                                models = account_models.get(acc.id, [])
                                acc_balance = acc.balance_remaining
                                acc_balance_unit = acc.balance_unit
                                acc_daily = acc.daily_used_tokens or 0
                                acc_prompt = acc.total_prompt_tokens or 0
                                acc_comp = acc.total_completion_tokens or 0

                                # 账号卡片（主行）：key 标识 + 默认模型名（从行模型不再与账号重名）
                                with ui.card().classes('w-full shadow-sm border-l-4 border-l-blue-500'):
                                    with ui.row().classes('w-full items-center gap-2 px-3 py-2 cursor-pointer hover:bg-gray-100 transition-colors flex-wrap wg-row-click') as a_header:
                                        ui.icon('account_circle', size='md').classes('text-blue-600')
                                        acc_key = mask_key(acc)
                                        with ui.column().classes('gap-0'):
                                            ui.label(acc_key if acc_key else '本地模型（无密钥）').classes('text-sm font-bold text-gray-800 font-mono')
                                            ui.label(f'默认模型 {acc.default_model_name or "未命名"}').classes('text-xs text-gray-400')
                                        ui.badge(f'{len(models)} 个模型', color='purple').classes('text-xs')
                                        ui.badge('✅ 启用' if acc.is_enable else '❌ 停用',
                                                 color='positive' if acc.is_enable else 'negative').props(f'data-acc-badge="{acc.id}"').classes('text-xs')
                                        if not getattr(acc, 'key_verified', True):
                                            ui.badge('⚠ Key未验证', color='warning').props(f'data-acc-keywarn="{acc.id}"').classes('text-xs')
                                        from app.admin.admin import show_account_dialog, toggle_account_enable
                                        ui.button('编辑', on_click=lambda aid=acc.id: show_account_dialog(account_id=aid)).props('outline size=xs color=primary').classes('text-xs').on('click', lambda: None, ['stop'])
                                        ui.button('停用', on_click=lambda aid=acc.id: toggle_account_enable(aid, False)).props(f'outline size=xs color=warning data-acc-btn="{acc.id}" data-acc-action="disable"').classes('text-xs' + ('' if acc.is_enable else ' hidden')).on('click', lambda: None, ['stop'])
                                        ui.button('启用', on_click=lambda aid=acc.id: toggle_account_enable(aid, True)).props(f'outline size=xs color=positive data-acc-btn="{acc.id}" data-acc-action="enable"').classes('text-xs' + ('' if not acc.is_enable else ' hidden')).on('click', lambda: None, ['stop'])
                                        a_icon = ui.icon('expand_more', size='sm').classes('text-gray-400 ml-auto')

                                    # 模型清单（从行）
                                    with ui.column().classes('w-full px-3 pb-3 gap-2') as a_area:
                                        a_area.visible = False
                                        if models:
                                            ui.label('账号已停用：以下模型不参与路由（模型状态保留，重新启用后恢复）') \
                                                .props(f'data-acc-warn="{acc.id}"').classes('text-xs text-red-500 font-bold' + ('' if not acc.is_enable else ' hidden'))
                                            with ui.row().classes('items-center w-full mt-1'):
                                                ui.label('模型清单').classes('text-xs font-bold text-gray-500')
                                                ui.space()
                                                ui.button('添加模型', on_click=lambda aid=acc.id: show_account_dialog(account_id=aid)) \
                                                    .props('outline size=xs color=orange no-caps').classes('text-xs').on('click', lambda: None, ['stop'])
                                            from app.admin.admin import show_model_capability_dialog, toggle_model_active, _type_label
                                            for model in models:
                                                m_cls = 'w-full shadow-sm cursor-pointer hover:bg-gray-100 transition-colors wg-row-click' + ('' if model.is_active else ' opacity-60')
                                                with ui.card().classes(m_cls).props(f'data-model-card="{model.id}"').on('click', lambda mid=model.id: show_model_capability_dialog(mid)):
                                                    with ui.row().classes('items-center gap-2 w-full flex-wrap'):
                                                        ui.icon('smart_toy', size='sm').classes('text-blue-500')
                                                        ui.label(model.display_name or model.model_name).classes('text-sm font-bold text-gray-700')
                                                        ui.badge(_type_label(model.model_type), color='blue').classes('text-xs')
                                                        _in_p = model.input_price
                                                        _out_p = model.output_price
                                                        if (_in_p is not None and _in_p > 0) or (_out_p is not None and _out_p > 0):
                                                            ui.badge(f'￥{_in_p or 0:.2f}/{_out_p or 0:.2f} 每1M', color='teal').classes('text-xs')
                                                        elif _in_p is not None and _out_p is not None:
                                                            # 两者都有值且都不大于 0 → 确定免费
                                                            ui.badge('🆓 免费', color='green').classes('text-xs')
                                                        else:
                                                            # 价格未知（未获取）
                                                            ui.badge('单价未获取', color='grey').classes('text-xs')
                                                        if model.embedding_vector:
                                                            ui.badge('向量已算', color='purple').classes('text-xs')
                                                        else:
                                                            ui.badge('向量未算', color='grey').classes('text-xs')
                                                        ui.badge(f'示例 {len(model.examples) if model.examples else 0} 条', color='teal').classes('text-xs')
                                                        ui.button('能力', on_click=lambda mid=model.id: show_model_capability_dialog(mid)).props('outline size=xs color=purple').classes('text-xs').on('click', lambda: None, ['stop'])
                                                        ui.button('停用', on_click=lambda mid=model.id: toggle_model_active(mid, False)).props(f'outline size=xs color=warning data-model-btn="{model.id}" data-model-action="disable"').classes('text-xs' + ('' if model.is_active else ' hidden')).on('click', lambda: None, ['stop'])
                                                        ui.button('启用', on_click=lambda mid=model.id: toggle_model_active(mid, True)).props(f'outline size=xs color=positive data-model-btn="{model.id}" data-model-action="enable"').classes('text-xs' + ('' if not model.is_active else ' hidden')).on('click', lambda: None, ['stop'])
                                                        ui.icon('chevron_right', size='sm').classes('text-gray-300 ml-auto')

                                                    if model.capability_description:
                                                        desc = model.capability_description[:100] + ('...' if len(model.capability_description) > 100 else '')
                                                        ui.label(desc).classes('text-xs text-gray-500 mt-1')

                                                    with ui.row().classes('items-center gap-4 mt-1 flex-wrap'):
                                                        ui.label(f'累计: 输入{acc_prompt / 1_000_000:.2f}M / 输出{acc_comp / 1_000_000:.2f}M tokens').classes('text-xs text-gray-500')
                                                        ui.label(f'当日: {acc_daily:,} tokens').classes('text-xs text-gray-500')
                                                        if acc_balance is not None and acc_balance_unit:
                                                            if acc_balance_unit == 'token':
                                                                ui.label(f'余额: {acc_balance:,.0f} tokens').classes('text-xs font-bold text-blue-600')
                                                            else:
                                                                ui.label(f'余额: ¥{acc_balance:.2f}').classes('text-xs font-bold text-blue-600')
                                        else:
                                            ui.label('该账号下暂无模型，点击「编辑」配置模型').classes('text-xs text-gray-400')

                                    async def toggle_a(area=a_area, icon=a_icon):
                                        area.visible = not area.visible
                                        icon.props(f'name={"expand_more" if not area.visible else "expand_less"}')
                                    a_header.on('click', toggle_a)

                                    # ── 插件挂载点：account.card.footer ──
                                    account_footer_components = component_registry.get_sorted(UI_HOOK_ACCOUNT_CARD_FOOTER)
                                    if account_footer_components:
                                        ui.separator().classes('my-1')
                                        for comp in account_footer_components:
                                            try:
                                                render_fn = comp['render']
                                                if callable(render_fn):
                                                    result = render_fn(acc)
                                                    if hasattr(result, '__await__'):
                                                        await result
                                            except Exception as e:
                                                with ui.row().classes('items-center gap-2 px-2 py-1 bg-red-50 rounded'):
                                                    ui.icon('error', size='sm').classes('text-red-500')
                                                    ui.label(f'插件组件异常: {e}').classes('text-xs text-red-600')

                        async def toggle_v(area=v_area, icon=v_icon):
                            area.visible = not area.visible
                            icon.props(f'name={"expand_more" if not area.visible else "expand_less"}')
                        v_header.on('click', toggle_v)
            else:
                with ui.card().classes('w-full text-center p-12'):
                    ui.icon('info', size='4rem').classes('text-gray-400')
                    ui.label('暂无账号').classes('text-xl text-gray-500 mt-4')
                    ui.label('点击右上角"新增账号"按钮添加第一个账号').classes('text-sm text-gray-400')
