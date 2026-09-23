"""
免费向导页面
"""
from __future__ import annotations
from nicegui import ui
from .base import BasePage


class WizardPage(BasePage):
    """免费向导"""

    async def render(self):
        """渲染免费向导页面"""
        ui.add_head_html('''
        <style>
          .vendor-list .q-card { border: 2px solid transparent; }
          .vendor-list .q-card[data-sel="1"] { border: 2px solid #52c41a !important; }
          .vendor-list .q-card.local-card { border: 2px solid #22d3ee !important; background: linear-gradient(135deg, #f0fdff 0%, #ffffff 60%); }
          .vendor-list .q-card.local-card[data-sel="1"] { border-color: #0891b2 !important; }
          .vendor-list .q-card.custom-card { border: 2px dashed #fb923c !important; background: linear-gradient(135deg, #fffaf5 0%, #ffffff 70%); }
          .vendor-list .q-card.custom-card[data-sel="1"] { border-color: #ea580c !important; background: #fff3e6; }
        </style>
        ''')

        from app.services.free_tier_catalog import list_vendors_merged, get_vendor_merged, FreeTierService, vendor_matches
        from app.services.model_catalog import ModelCatalogService
        from app.utils.encryption import encryption_service
        from app.models import AsyncSessionLocal
        from app.models.database import ModelAccount, ModelCatalog
        from sqlalchemy import select

        extra_inputs = {}            # extra 字段输入框引用（detail 重建后重填）

        # 合并目录（内置 + DB 用户覆盖）+ 已接入厂商标记（按别名匹配，避免同名不同写法漏判）
        async with AsyncSessionLocal() as _s:
            vendors = await list_vendors_merged(_s)
            # 主从架构：模型挂在 ModelCatalog 下，从 catalog 统计已接入模型
            cat_res = await _s.execute(select(ModelCatalog.vendor, ModelCatalog.model_name))
            _vendor_models = [(r[0] or '', r[1]) for r in cat_res.all()]
        state = {'selected': (vendors[1] if len(vendors) > 1 else (vendors[0] if vendors else None))}   # 默认选中第二个厂商（右侧详情同步打开）

        def vendor_connected(v):
            return any(vendor_matches(vn, v['id']) for vn, _ in _vendor_models)

        def vendor_connected_models(v):
            return [mn for vn, mn in _vendor_models if vendor_matches(vn, v['id'])]

        def select_vendor(v):
            state['selected'] = v
            # 只刷新详情，左侧卡片区不重绘（避免滚动位置重置）；选中高亮用 JS 按唯一 data-vendor-id 切换
            detail.refresh()
            ui.run_javascript(f"""
                const list = document.querySelector('.vendor-list');
                if (!list) return;
                list.querySelectorAll('.q-card').forEach(c => c.removeAttribute('data-sel'));
                const cur = list.querySelector('.q-card[data-vendor-id="{v['id']}"]');
                if (cur) cur.setAttribute('data-sel', '1');
            """)

        def select_custom():
            """选择自定义厂商入口（虚线卡片）"""
            state['selected'] = {'id': '__custom__', 'name': '其他厂商（自定义接入）'}
            detail.refresh()
            ui.run_javascript("""
                const list = document.querySelector('.vendor-list');
                if (!list) return;
                list.querySelectorAll('.q-card').forEach(c => c.removeAttribute('data-sel'));
                const cur = list.querySelector('.q-card[data-vendor-id="__custom__"]');
                if (cur) cur.setAttribute('data-sel', '1');
            """)

        async def run_config(v, api_key_input):
            nonlocal _vendor_models
            key = (api_key_input.value or '') if api_key_input else ''
            if not v.get('no_key') and not key:
                # 留空 = 沿用该厂商已有 Key（auto_configure 内决策）；从未配置过才拦截
                has_key = False
                async with AsyncSessionLocal() as _s:
                    for _a in (await _s.execute(select(ModelAccount).where(ModelAccount.api_key_encrypted.isnot(None)))).scalars().all():
                        if _a.api_key_encrypted and vendor_matches(_a.vendor or '', v['id']):
                            has_key = True
                            break
                if not has_key:
                    ui.notify('请先粘贴 API Key（该厂商尚未配置过）', type='warning')
                    return
            try:
                extra = {k: inp.value for k, inp in extra_inputs.items()}
                async with AsyncSessionLocal() as session:
                    svc = FreeTierService(session)
                    res = await svc.auto_configure(v['id'], key, extra)
                parts = []
                if res['created_accounts']:
                    parts.append(f"新建 {len(res['created_accounts'])} 个账号")
                if res['models_synced']:
                    parts.append(f"同步 {len(res['models_synced'])} 个模型")
                if res['balance']:
                    parts.append(f"余额 {res['balance'][1]:.2f} {res['balance'][0]}")
                if res['skipped']:
                    parts.append(f"跳过 {len(res['skipped'])} 个已存在")
                if res.get('keys_updated'):
                    parts.append(f"统一更新 {len(res['keys_updated'])} 个模型 Key")
                if res['errors']:
                    parts.append(f"错误 {len(res['errors'])} 个: {'; '.join(res['errors'][:2])}")
                # Key 验证状态
                notify_type = 'positive'
                if not res.get('key_validated', True):
                    notify_type = 'warning'
                    err = res.get('key_validation_error') or ''
                    parts.append(f"⚠ Key 未验证（可能无效）: {err[:60]}")
                ui.notify(res['vendor'] + " 配置完成 " + " | ".join(parts), type=notify_type, timeout=8000)
                # 重新查询已接入信息并局部刷新（从 ModelCatalog 统计）
                async with AsyncSessionLocal() as session:
                    cat_res = await session.execute(select(ModelCatalog.vendor, ModelCatalog.model_name))
                    _vendor_models = [(r[0] or '', r[1]) for r in cat_res.all()]
                cards.refresh()
                detail.refresh()
            except Exception as e:
                ui.notify(f'配置失败: {str(e)[:150]}', type='negative')

        async def run_custom_config(name_input, key_input, model_input):
            """自定义厂商一键接入：幂等（同 key 密文判重）→ 建账号 → 智能开通模型"""
            nonlocal _vendor_models
            name = (name_input.value or '').strip()
            key = (key_input.value or '').strip()
            model = (model_input.value or '').strip() or 'chat'
            if not name:
                ui.notify('请填写厂商名称', type='warning')
                return
            if not key:
                ui.notify('请粘贴 API 密钥', type='warning')
                return
            try:
                enc = encryption_service.encrypt(key)
                async with AsyncSessionLocal() as session:
                    # 注意：Fernet 加密非确定性，必须解密后比较明文，不能用密文查询
                    all_accs = (await session.execute(select(ModelAccount))).scalars().all()
                    exists = None
                    for a in all_accs:
                        try:
                            if a.api_key_encrypted and encryption_service.decrypt(a.api_key_encrypted) == key:
                                exists = a
                                break
                        except Exception:
                            continue
                    if exists:
                        ui.notify(f'该 Key 已接入（厂商「{exists.vendor} · {exists.default_model_name}」），无需重复配置；如需加模型请到账号管理编辑', type='warning')
                        return
                    acc = ModelAccount(vendor=name, api_key_encrypted=enc, model_name=model, is_enable=True)
                    session.add(acc)
                    await session.commit()
                    await session.refresh(acc)
                    svc = ModelCatalogService(session)
                    await svc.ensure_model(model, name, account_id=acc.id)
                    await session.commit()
                # 刷新已接入标记（从 ModelCatalog 统计）
                async with AsyncSessionLocal() as session:
                    cat_res = await session.execute(select(ModelCatalog.vendor, ModelCatalog.model_name))
                    _vendor_models = [(r[0] or '', r[1]) for r in cat_res.all()]
                ui.notify(f'已接入「{name} · {model}」，向量/能力已智能计算', type='positive', timeout=5000)
                cards.refresh()
                detail.refresh()
            except Exception as e:
                ui.notify(f'接入失败: {str(e)[:150]}', type='negative')

        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            ui.label('🆓 免费向导').classes('text-3xl font-bold text-gray-800')
            ui.label('选一个厂商 → 按步骤拿到 API Key → 粘贴后自动完成建账号、能力描述、向量计算、启用。全程 10 分钟以内，无需理解任何底层概念').classes('text-[13px] text-gray-500 -mt-2')

            # 区块标题（行外，左右两栏从同一水平线开始，详情与卡片上缘对齐）
            with ui.row().classes('items-center gap-3 w-full -mt-1'):
                ui.label('① 选择厂商').classes('text-xl font-bold text-gray-700')
                ui.label('点击左侧卡片，右侧展示接入步骤与一键配置').classes('text-xs text-gray-400')

            with ui.row().classes('w-full gap-6 items-start'):
                # ── 左：厂商卡片（列表独立滚动）──
                with ui.column().classes('w-[40%] min-w-[480px] gap-3 vendor-list'):
                    @ui.refreshable
                    def cards():
                        from app.admin.admin import vendor_icon_html
                        # 瀑布流：CSS grid 固定两列，各自自适应高度；整卡可点，点击只 JS 高亮 + 刷详情
                        # 滚动区独立于右侧详情；自定义卡作为最后一行横跨两列
                        with ui.element('div').classes('w-full h-[calc(100vh-235px)] overflow-y-auto pr-1').style('display:grid;grid-template-columns:1fr 1fr;gap:12px;align-content:start'):
                            for col_vendors in (vendors[::2], vendors[1::2]):
                                for v in col_vendors:
                                    is_sel = state['selected'] and state['selected']['id'] == v['id']
                                    is_local = v.get('no_key', False)
                                    card_cls = 'w-full shadow-lg cursor-pointer hover:shadow-xl transition-all p-3' + (' local-card' if is_local else '')
                                    with ui.card().classes(card_cls).props(
                                        f'data-sel={"1" if is_sel else "0"} data-vendor-id="{v["id"]}"'
                                    ).on('click', lambda vv=v: select_vendor(vv)):
                                        with ui.row().classes('items-center gap-2 w-full'):
                                            ui.html(vendor_icon_html(v.get('icon', ''), 'w-7 h-7 rounded object-contain'), sanitize=False)
                                            ui.label(v['name']).classes('text-base font-bold')
                                        ui.label(v['tag']).classes(('text-xs text-cyan-600 font-bold' if is_local else 'text-xs text-green-600 font-bold'))
                                        with ui.row().classes('items-center gap-1 w-full'):
                                            _fc = v.get('free_count', 0)
                                            ui.label(f"{_fc} 个免费模型" if _fc > 0 else f"{len(v['models'])} 个模型").classes('text-xs text-gray-500')
                                            if vendor_connected(v):
                                                ui.label(f'已接入 {len(vendor_connected_models(v))} 个').classes('text-xs text-green-600 font-bold')
                                        # 免费模型具体名称（与模型菜单卡片一致；list_vendors_merged 已预计算 free_models）
                                        free_displays = v.get('free_models', [])
                                        if free_displays:
                                            ui.label(f"{'、'.join(free_displays[:3])}{'…' if len(free_displays) > 3 else ''}").classes('text-[11px] text-green-700')
                                        ui.label(v['quota_note']).classes('text-xs text-gray-500').style('line-height:1.35')
                                        if v.get('access_note'):
                                            ui.label(f"⚠️ {v['access_note']}").classes('text-xs text-orange-600 font-bold').style('line-height:1.3')
                                        ui.button('选择', on_click=lambda vv=v: select_vendor(vv)) \
                                            .props('color=green outline size=sm no-caps').classes('w-full mt-1 wg-select-vendor')

                            # 自定义厂商入口：瀑布最后一行，横跨两列（仍在滚动区内）
                            with ui.column().style('grid-column:1 / -1').classes('w-full min-w-0 gap-1'):
                                is_custom_sel = state['selected'] and state['selected']['id'] == '__custom__'
                                with ui.card().classes('w-full custom-card shadow cursor-pointer hover:shadow-xl transition-all p-3').props(
                                    f'data-sel={"1" if is_custom_sel else "0"} data-vendor-id="__custom__"'
                                ).on('click', lambda: select_custom()):
                                    with ui.row().classes('items-center gap-2 w-full'):
                                        ui.icon('add_circle', size='md').classes('text-orange-500')
                                        ui.label('其他厂商 · 自定义接入').classes('text-base font-bold text-orange-600')
                                    ui.label('厂商目录里没有你的厂商？填厂商名 + API Key 即可接入，向量/能力自动计算').classes('text-xs text-gray-500').style('line-height:1.35')
                                    ui.label('自定义厂商（自由输入，自动创建账号）').classes('text-xs bg-orange-50 text-orange-700 px-2 py-0.5 rounded font-bold')

                    cards()
                # ── 右：详情 / 配置区（独立滚动）──
                with ui.column().classes('flex-1 min-w-0 gap-2 h-[calc(100vh-235px)] overflow-y-auto pr-1'):
                    @ui.refreshable
                    async def detail():
                        from app.admin.admin import vendor_icon_html
                        v = state['selected']
                        if not v:
                            with ui.card().classes('w-full shadow p-8'):
                                ui.label('点击左侧卡片选择一个厂商').classes('text-gray-400 text-center py-16 w-full')
                            return
                        if v.get('id') == '__custom__':
                            with ui.card().classes('w-full shadow-lg border-l-4 border-dashed border-l-orange-400 p-3'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('add_circle', size='md').classes('text-orange-500')
                                    ui.label('其他厂商 · 自定义接入').classes('text-lg font-bold text-orange-700')
                                ui.label('厂商目录里没有你的厂商？直接填厂商名和 API Key，创建账号并自动接入模型（向量/能力智能计算）').classes('text-xs text-gray-500 mt-0.5').style('line-height:1.35')
                                ui.label('① 填写厂商信息（厂商名 = 你注册的平台名称）').classes('text-sm font-bold text-gray-700 mt-2')
                                c_name = ui.input('厂商名称（如：某某开放平台）', placeholder='自定义厂商名，保存后自动创建分组').props('dense outlined').classes('w-full')
                                c_key = ui.input('API 密钥', password=True, password_toggle_button=True, placeholder='粘贴你的 API Key').props('dense outlined').classes('w-full')
                                c_model = ui.input('默认模型（该 Key 下可调用的模型名）', value='chat', placeholder='如：gpt-4o-mini / deepseek-chat').props('dense outlined').classes('w-full')
                                with ui.row().classes('w-full justify-end'):
                                    ui.button('一键智能接入', on_click=lambda: run_custom_config(c_name, c_key, c_model)) \
                                        .props('color=orange size=md no-caps').classes('wg-custom-config-btn')
                            return
                        async with AsyncSessionLocal() as ds:
                            full = await get_vendor_merged(ds, v['id']) or v
                        with ui.card().classes('w-full shadow-lg border-l-4 border-green-500 p-3'):
                            with ui.row().classes('items-center gap-2'):
                                ui.html(vendor_icon_html(v.get('icon', ''), 'w-7 h-7 rounded object-contain'), sanitize=False)
                                ui.label(v['name']).classes('text-lg font-bold')
                                ui.label(v['tag']).classes('text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded font-bold')
                            ui.label(f"额度说明：{v['quota_note']}").classes('text-[13px] text-gray-600 mt-0.5').style('line-height:1.35')
                            if v.get('access_note'):
                                ui.label(f"⚠️ {v['access_note']}").classes('text-xs text-orange-600 font-bold mt-0.5')
                            connected_models = vendor_connected_models(v)
                            free_cnt = v.get('free_count', 0)
                            total_cnt = len(v['models'])
                            if connected_models:
                                _has_free = free_cnt > 0
                                _model_word = '免费模型' if _has_free else '模型'
                                if total_cnt > 0 and len(connected_models) >= total_cnt:
                                    ui.label(f'该厂商{_model_word}已全部接入，无需重复配置；如需更换 Key 请到账号管理编辑').classes('text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded mt-0.5')
                                else:
                                    ui.label(f"已接入 {len(connected_models)}/{total_cnt} 个，只补充未接入的{_model_word}").classes('text-xs text-blue-700 bg-blue-50 px-2 py-0.5 rounded mt-0.5')
                            free_displays = v.get('free_models', [])
                            if free_displays:
                                ui.label(f"免费模型：{'、'.join(free_displays[:4])}{'…' if len(free_displays) > 4 else ''}").classes('text-xs text-gray-600 mt-0.5')

                            is_no_key = v.get('no_key', False)
                            if is_no_key:
                                ui.label('② 准备本地模型（无需 API Key）').classes('text-sm font-bold text-gray-700 mt-2')
                                for i, step in enumerate(full['steps'], 1):
                                    with ui.row().classes('items-start gap-1.5 w-full'):
                                        ui.label(str(i)).classes('w-5 h-5 rounded-full bg-green-500 text-white text-xs flex items-center justify-center mt-0.5')
                                        ui.label(step).classes('text-[13px] flex-1 pt-0.5').style('line-height:1.3')
                                ui.label('③ 一键智能配置（自动探测本地已安装模型）').classes('text-sm font-bold text-gray-700 mt-2')
                                api_key_input = None
                            else:
                                ui.label('② 获取 API Key（只需这一步）').classes('text-sm font-bold text-gray-700 mt-2')
                                # 注册链接放在步骤上方，与步骤①"打开上方链接"文案一致
                                ui.link(f'前往 {v["name"]} 获取 API Key', v['signup_url'], new_tab=True) \
                                    .classes('text-blue-600 underline text-[13px] mt-0.5')
                                for i, step in enumerate(full['steps'], 1):
                                    with ui.row().classes('items-start gap-1.5 w-full'):
                                        ui.label(str(i)).classes('w-5 h-5 rounded-full bg-green-500 text-white text-xs flex items-center justify-center mt-0.5')
                                        ui.label(step).classes('text-[13px] flex-1 pt-0.5').style('line-height:1.3')
                                ui.label('③ 粘贴 API Key，一键智能配置').classes('text-sm font-bold text-gray-700 mt-2')
                                key_tail = None
                                async with AsyncSessionLocal() as _ds2:
                                    for a in (await _ds2.execute(select(ModelAccount).where(ModelAccount.api_key_encrypted.isnot(None)))).scalars().all():
                                        if a.api_key_encrypted and vendor_matches(a.vendor or '', v['id']):
                                            try:
                                                k = encryption_service.decrypt(a.api_key_encrypted)
                                                if k:
                                                    key_tail = k[-4:]
                                                    break
                                            except Exception:
                                                pass
                                if key_tail:
                                    ui.label(f'已配置 Key：****{key_tail}（留空沿用旧 Key；填新 Key 将统一更换该厂商所有模型的 Key）') \
                                        .classes('text-xs text-green-700 bg-green-50 border border-green-200 px-2 py-1 rounded w-full mt-1')
                                key_ph = f"已配置 Key（…{key_tail}），可留空沿用" if key_tail else "粘贴你的 API Key"
                                api_key_input = ui.input('API Key', password=True, password_toggle_button=True, placeholder=key_ph) \
                                    .props('dense outlined').classes('w-full')
                                for f in v.get('extra_fields', []):
                                    extra_inputs[f['key']] = ui.input(f['label'], placeholder=f.get('placeholder', '')) \
                                        .props('dense outlined').classes('w-full')

                            with ui.row().classes('w-full justify-end'):
                                ui.button('一键智能配置', on_click=lambda: run_config(v, api_key_input)) \
                                    .props('color=green size=md no-caps').classes('wg-config-btn')

                    ui.timer(0.01, detail, once=True)
