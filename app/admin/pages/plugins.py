"""
插件管理页面
"""
from __future__ import annotations
from typing import Optional
from nicegui import ui
from starlette.requests import Request
from .base import BasePage


class PluginsPage(BasePage):
    """插件管理"""

    def __init__(self, db=None, config=None, request: Optional[Request] = None, plugin_active: str = None):
        super().__init__(db, config)
        self.request = request
        self.plugin_active = plugin_active

    async def render(self):
        """渲染插件管理页面"""
        def make_plugin_click_handler(p):
            def handler():
                js = (
                    'var container=document.getElementById("plugin-detail-scroll");'
                    f"var el=container?container.querySelector('[data-plugin=\"{p}\"]'):document.querySelector('[data-plugin=\"{p}\"]');"
                    'if(el&&container){'
                    'var targetTop=el.offsetTop-container.offsetTop+container.scrollTop-16;'
                    'container.scrollTo({top:targetTop,behavior:"smooth"});'
                    'var blinkCount=0;var blinkInterval=setInterval(function(){'
                    'if(blinkCount%2===0){el.classList.add("ring-2","ring-blue-400")}else{el.classList.remove("ring-2","ring-blue-400")};'
                    'blinkCount++;if(blinkCount>=10){clearInterval(blinkInterval);el.classList.remove("ring-2","ring-blue-400")}},500);'
                    '}else if(el){el.scrollIntoView({behavior:"smooth",block:"center"});}'
                )
                ui.run_javascript(js)
            return handler

        @ui.refreshable
        async def render_content():
            """统一渲染：根据 plugin_active 全局状态决定显示插件详情或插件管理"""
            self.refresh = render_content.refresh  # 暴露 refresh 函数供外部调用
            if self.plugin_active:
                # ═══ 插件详情页面 ═══
                from app.extensions.sdk import page_registry, nav_registry
                active_plugin = self.plugin_active
                # 查找插件路由
                plugin_route = None
                plugin_info = None
                for nav_item in nav_registry.list():
                    nav_key = nav_item['route'].strip('/')
                    # 兼容连字符/下划线变体（hello-world vs hello_world）
                    if (nav_key == active_plugin or nav_key == active_plugin.replace('_', '-')
                            or nav_key.replace('-', '_') == active_plugin):
                        plugin_route = nav_item['route']
                        plugin_info = nav_item
                        break

                with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
                    # 插件页面顶部：返回按钮 + 插件名称
                    with ui.row().classes('items-center justify-between w-full'):
                        from app.admin.admin import spa_navigate
                        with ui.row().classes('items-center gap-3'):
                            ui.button('← 返回插件管理', on_click=lambda: spa_navigate('plugins')).props('outline color=primary')
                            ui.label(plugin_info['label'] if plugin_info else active_plugin).classes('text-2xl font-bold text-gray-800')
                        # 插件切换下拉
                        plugin_options = {nav_item['route'].strip('/'): nav_item['label'] for nav_item in nav_registry.list()}
                        current_key = plugin_route.strip('/') if plugin_route else active_plugin
                        # 安全检查：value 必须在 options 中，否则 NiceGUI 抛 ValueError
                        select_value = current_key if current_key in plugin_options else (next(iter(plugin_options)) if plugin_options else None)
                        def on_plugin_change(e):
                            spa_navigate('plugins', active=e.value)
                        ui.select(options=plugin_options, value=select_value, on_change=on_plugin_change, label='切换插件').props('outlined dense').classes('w-48')

                    # 插件内容区域
                    if plugin_route and plugin_route in page_registry.list():
                        page_info = page_registry.get(plugin_route)
                        if page_info and callable(page_info['render']):
                            try:
                                render_func = page_info['render']
                                import inspect as _inspect
                                _sig = _inspect.signature(render_func)
                                result = render_func(self.request) if 'request' in _sig.parameters else render_func()
                                if hasattr(result, '__await__'):
                                    await result
                            except Exception as e:
                                with ui.card().classes('w-full bg-red-50 border-l-4 border-red-500 p-4'):
                                    ui.label(f'插件页面渲染异常: {e}').classes('text-red-700')
                    else:
                        with ui.card().classes('w-full p-8 text-center'):
                            ui.label(f'未找到插件: {active_plugin}').classes('text-xl text-gray-500')
            else:
                # ═══ 插件管理页面 ═══
                from app.extensions.loader import get_plugin_registry, get_plugin_stats
                from app.extensions.sdk import config_registry as _cfg_reg, get_plugin_config, set_plugin_config, nav_registry

                stats = get_plugin_stats()
                registry = get_plugin_registry()
                all_configs = _cfg_reg.list()

                with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
                    # ═══ 标题 ═══
                    with ui.row().classes('items-center justify-between w-full'):
                        ui.label('🔌 插件管理').classes('text-3xl font-bold text-gray-800')
                        ui.button('🔄 刷新', on_click=render_content.refresh).props('outline color=primary')

                    # ═══ 一、概览统计 ═══
                    def stat_card(icon, title, value, sub=None, color='blue'):
                        with ui.card().classes(f'flex-1 border-l-4 border-{color}-500 p-4').style('min-height:120px'):
                            with ui.column().classes('w-full items-center gap-2 justify-center').style('min-height:100%'):
                                ui.label(icon).classes('text-2xl')
                                ui.label(str(value)).classes('text-3xl font-bold')
                                ui.label(title).classes('text-sm text-gray-600 font-medium')
                                if sub:
                                    ui.label(sub).classes('text-xs text-gray-400')

                    with ui.row().classes('w-full gap-3'):
                        stat_card('📦', '已加载插件', f'{stats["loaded_plugins"]}/{stats["total_plugins"]}', f'失败 {stats["failed_plugins"]}', 'green')
                        stat_card('🔌', '生命周期钩子', stats['hook_count'], f'{len(stats["hook_events"])} 个事件', 'blue')
                        stat_card('⚙️', 'SPI 策略实现', stats['spi_count'], f'{len(stats["spi_types"])} 种类型', 'purple')
                        stat_card('🖥️', 'UI 扩展点', stats.get('ui_pages', 0) + stats.get('ui_nav_items', 0) + stats.get('ui_components', 0),
                                  f'页面{stats.get("ui_pages",0)} 导航{stats.get("ui_nav_items",0)} 组件{stats.get("ui_components",0)}', 'orange')

                # ═══ 二、概念说明（可折叠）═══
                with ui.card().classes('w-full'):
                    with ui.column().classes('gap-3 p-4'):
                        with ui.row().classes('items-center justify-between w-full'):
                            ui.label('📚 概念体系说明').classes('text-lg font-bold text-gray-800')
                            concept_expand = ui.icon('expand_more', size='sm').classes('cursor-pointer text-gray-500')

                        concept_content = ui.column().classes('w-full gap-3')
                        concept_content.visible = False

                        def toggle_concept():
                            concept_content.visible = not concept_content.visible
                            concept_expand.props(f'name={"expand_less" if concept_content.visible else "expand_more"}')

                        concept_expand.on('click', toggle_concept)

                        with concept_content:
                            # Hook 说明
                            with ui.card().classes('w-full bg-blue-50 border-l-4 border-blue-500'):
                                with ui.column().classes('gap-1 p-3'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label('🔌 Hook（钩子）').classes('font-bold text-blue-800')
                                        ui.badge('生命周期事件回调', color='info').props('outline')
                                    ui.label('定义：在程序执行的特定时间点触发的回调函数，用于插入自定义逻辑。').classes('text-sm text-blue-700')
                                    ui.label('应用场景：请求前过滤（route.before）、请求后处理（route.after）、启动初始化（app.startup）等。').classes('text-xs text-blue-600')
                                    ui.label('使用方式：register_hook(event_name, callback_func)').classes('text-xs font-mono text-blue-800 bg-white p-1 rounded')

                            # SPI 说明
                            with ui.card().classes('w-full bg-purple-50 border-l-4 border-purple-500'):
                                with ui.column().classes('gap-1 p-3'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label('⚙️ SPI（服务提供者接口）').classes('font-bold text-purple-800')
                                        ui.badge('策略扩展点', color='secondary').props('outline')
                                    ui.label('定义：定义了一组接口规范，插件可以实现这些接口来替换或扩展系统的核心策略。').classes('text-sm text-purple-700')
                                    ui.label('应用场景：自定义路由策略（RouteStrategy）、自定义账号选择策略（AccountSelector）等。').classes('text-xs text-purple-600')
                                    ui.label('使用方式：实现 SPI 接口类 + register_spi(spi_type, implementation)').classes('text-xs font-mono text-purple-800 bg-white p-1 rounded')

                            # Plugin 说明
                            with ui.card().classes('w-full bg-green-50 border-l-4 border-green-500'):
                                with ui.column().classes('gap-1 p-3'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label('📦 Plugin（插件）').classes('font-bold text-green-800')
                                        ui.badge('独立功能模块', color='positive').props('outline')
                                    ui.label('定义：一个独立的 Python 模块，通过注册 Hook/SPI/UI扩展点来扩展系统功能，可独立启用/禁用。').classes('text-sm text-green-700')
                                    ui.label('应用场景：余额监控插件、审计日志插件、自定义路由插件等完整功能。').classes('text-xs text-green-600')
                                    ui.label('使用方式：环境变量 WOOLGATE_PLUGINS=module.path，插件在 import 时自动注册扩展点').classes('text-xs font-mono text-green-800 bg-white p-1 rounded')

                            # UI扩展点说明
                            with ui.card().classes('w-full bg-orange-50 border-l-4 border-orange-500'):
                                with ui.column().classes('gap-1 p-3'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label('🖥️ UI 扩展点').classes('font-bold text-orange-800')
                                        ui.badge('界面注入点', color='warning').props('outline')
                                    ui.label('定义：管理后台界面中预设的注入位置，插件可以在这些位置添加自定义页面、导航项或组件。').classes('text-sm text-orange-700')
                                    ui.label('应用场景：添加独立管理页面、添加导航菜单项、在首页添加小部件、在账号卡片添加信息等。').classes('text-xs text-orange-600')
                                    ui.label('使用方式：register_page() / register_nav_item() / register_component(hook_point, render_func)').classes('text-xs font-mono text-orange-800 bg-white p-1 rounded')

                with ui.row().classes('w-full gap-4 items-start flex-nowrap'):
                    # ═══ 四、接口插座概览 ═══
                    with ui.card().classes('flex-1 min-w-0'):
                        with ui.column().classes('gap-3 p-4'):
                            ui.label('🔌 接口插座概览（程序执行阶段）').classes('text-lg font-bold text-gray-800')
                            ui.label('绿色节点为已生效实现（含系统内置与用户插件），点击 📦 用户插件可跳转到右侧配置区域').classes('text-xs text-gray-500')

                            # 获取详细的钩子/SPI信息
                            hook_details = stats.get('hook_details', {})
                            spi_details = stats.get('spi_details', {})
                            plugins_info = stats.get('plugins', {})
                            user_plugin_names = {info.get('name', '') for info in plugins_info.values()}

                            # 流程节点定义：(阶段名, 钩子事件, SPI类型列表, 功能描述, 颜色)
                            stages = [
                                ('1. 请求接入', None, ['security'], '接收请求，安全校验', 'blue'),
                                ('2. 前置钩子', 'route.before', None, '插件可在此过滤/修改请求', 'cyan'),
                                ('3. 意图分类', None, ['classifier'], '智能分类请求类型', 'indigo'),
                                ('4. 路由决策', None, ['router'], '选择目标模型', 'purple'),
                                ('5. 账号选择', None, ['selector'], '选择具体账号/Key', 'violet'),
                                ('6. 上下文管理', None, ['context'], '会话上下文处理', 'pink'),
                                ('7. 执行转发', None, ['adapter'], '转发请求到厂商API', 'green'),
                                ('8. 后置钩子', 'route.after', None, '插件可在此处理响应', 'orange'),
                                ('9. 日志存储', None, ['store'], '记录请求/响应日志', 'gray'),
                            ]

                            with ui.row().classes('w-full items-start gap-2 flex-wrap justify-center'):
                                for i, (stage_name, hook_event, spi_types, desc, color) in enumerate(stages):
                                    # 收集该节点已注册的扩展点
                                    registered_items = []
                                    if hook_event and hook_event in hook_details:
                                        for hd in hook_details[hook_event]:
                                            registered_items.append({
                                                'type': 'Hook',
                                                'name': hook_event,
                                                'plugin': hd['plugin'],
                                                'function': hd['function'],
                                            })
                                    for st in (spi_types or []):
                                        if st in spi_details:
                                            for sd in spi_details[st]:
                                                registered_items.append({
                                                    'type': 'SPI',
                                                    'name': st,
                                                    'plugin': sd['plugin'],
                                                    'function': sd['name'],
                                                })

                                    is_active = len(registered_items) > 0
                                    border_color = 'green' if is_active else color

                                    with ui.column().classes('items-center gap-1'):
                                        card_classes = f'bg-{color}-50 border-2 border-{border_color}-400'
                                        if is_active:
                                            card_classes += ' shadow-md ring-2 ring-green-200'
                                        with ui.card().classes(card_classes).style('min-width:150px; max-width:180px; padding:8px;'):
                                            with ui.column().classes('items-center gap-1 w-full'):
                                                # 阶段名称
                                                ui.label(stage_name).classes(f'text-xs font-bold text-{color}-800')
                                                # 扩展点名称
                                                ext_name = hook_event or (spi_types[0] if spi_types else '')
                                                if ext_name:
                                                    ui.label(ext_name).classes(f'text-xs font-mono text-{color}-600')
                                                # 功能描述
                                                ui.label(desc).classes('text-xs text-gray-500 text-center')
                                                
                                                # 已注册的实现列表（区分系统内置和用户插件）
                                                if registered_items:
                                                    ui.label(f'已注册实现 ({len(registered_items)}):').classes('text-xs font-bold text-green-700 mt-1')
                                                    for item in registered_items:
                                                        plugin_name = item['plugin']
                                                        # 判断是否为系统内置实现：模块名以 app. 开头，或不在 plugins_info 中
                                                        is_builtin = plugin_name.startswith('app.') or plugin_name.startswith('app/') or plugin_name not in user_plugin_names
                                                        # 判断是否为系统内置实现：模块名以 app. 开头，或不在用户插件名称集合中
                                                        # 每个实现用一个小容器包裹
                                                        with ui.row().classes('items-center gap-1 w-full justify-center'):
                                                            if is_builtin:
                                                                # 系统内置实现，不可点击
                                                                ui.label('⚙️ 系统内置').classes('text-xs text-gray-500 bg-gray-100 px-1 rounded font-mono')
                                                                ui.label(plugin_name).classes('text-xs text-gray-400 font-mono')
                                                            else:
                                                                # 用户插件，通过 plugins_info 获取友好名称（统一大小写）
                                                                display_name = plugins_info[plugin_name].get('name', plugin_name) if plugin_name in plugins_info else plugin_name
                                                                # data-plugin 目标值统一用小写
                                                                target_name = display_name.lower()
                                                                ui.button(
                                                                    f'📦 {display_name}',
                                                                    on_click=make_plugin_click_handler(target_name)
                                                                ).props('flat dense color=green text-xs').classes('text-xs')
                                                            # 显示函数名和类型
                                                            ui.label(f'{item.get("type", "")}:{item.get("function", "")}').classes('text-xs text-gray-400 font-mono')
                                                    ui.badge('✓ 已生效', color='positive').props('outline').classes('text-xs mt-1')
                                                else:
                                                    ui.label('(预留扩展点)').classes('text-xs text-gray-400 italic')
                                    
                                    if i < len(stages) - 1:
                                        ui.icon('arrow_forward', size='sm').classes('text-gray-400 mx-1 mt-8')

                            # 统计摘要
                            with ui.row().classes('w-full gap-6 mt-2 pt-3 border-t'):
                                with ui.column().classes('gap-1'):
                                    ui.label(f'🔌 已注册钩子: {len(hook_details)} 个事件').classes('text-sm font-bold text-gray-700')
                                    if hook_details:
                                        for event, items in hook_details.items():
                                            ui.label(f'  • {event}: {len(items)} 个实现').classes('text-xs text-gray-500')
                                    else:
                                        ui.label('暂无插件注册钩子').classes('text-xs text-gray-400')
                                with ui.column().classes('gap-1'):
                                    ui.label(f'⚙️ 已注册SPI: {len(spi_details)} 种类型').classes('text-sm font-bold text-gray-700')
                                    if spi_details:
                                        for stype, items in spi_details.items():
                                            ui.label(f'  • {stype}: {len(items)} 个实现').classes('text-xs text-gray-500')
                                    else:
                                        ui.label('暂无插件注册SPI').classes('text-xs text-gray-400')
                    with ui.column().classes('flex-1 min-w-0 gap-4'):
                        # ═══ 三、插件列表（每个插件独立卡片，含配置）═══
                        with ui.row().classes('items-center gap-3 mt-2'):
                            ui.label('插件详情').classes('text-2xl font-bold text-gray-800')
                            # 插件清单按钮：点击显示所有插件的清单
                            plugin_list_btn = ui.button('📋 插件清单', icon='list').props('flat dense color=blue')
                            plugin_list_dialog = ui.dialog()
                            with plugin_list_dialog:
                                with ui.card().classes('w-[650px]'):
                                    ui.label('📋 插件清单').classes('text-xl font-bold text-gray-800')
                                    ui.label('所有已注册的插件及系统内置实现').classes('text-sm text-gray-500')
                                    ui.separator()
                                    # 用户插件列表（列表形式，支持多插件）
                                    if registry:
                                        ui.label(f'🔌 用户插件 ({len(registry)})').classes('text-sm font-bold text-green-700 mt-2')
                                        with ui.column().classes('w-full gap-2 max-h-[280px] overflow-y-auto pr-1'):
                                            for mod_name, p_info in registry.items():
                                                p_name = p_info.get('name', mod_name.split('.')[-1])
                                                p_ver = p_info.get('version', 'unknown')
                                                p_status = '✅ 已加载' if p_info['status'] == 'loaded' else '❌ 加载失败'
                                                p_desc = p_info.get('description', '')[:50]
                                                with ui.card().classes('w-full p-3 hover:bg-green-50 transition border-l-4 border-green-400'):
                                                    with ui.row().classes('items-center gap-2 w-full'):
                                                        ui.label(f'📦 {p_name}').classes('text-sm font-mono text-green-700 font-bold')
                                                        ui.label(f'v{p_ver}').classes('text-xs text-gray-400 bg-gray-100 px-1 rounded')
                                                        ui.label(p_status).classes('text-xs ml-auto')
                                                    ui.label(mod_name).classes('text-xs text-gray-400 font-mono mt-1')
                                                    if p_info.get('description'):
                                                        ui.label(p_info['description']).classes('text-xs text-gray-600 mt-1 leading-relaxed')
                                    # 系统内置实现列表（列表形式）
                                    ui.label(f'⚙️ 系统内置实现').classes('text-sm font-bold text-gray-600 mt-3')
                                    builtin_items = set()
                                    for event, items in hook_details.items():
                                        for item in items:
                                            pn = item['plugin']
                                            if pn.startswith('app.') or pn not in user_plugin_names:
                                                builtin_items.add((pn, item.get('type', ''), item.get('function', '')))
                                    for stype, items in spi_details.items():
                                        for item in items:
                                            pn = item['plugin']
                                            if pn.startswith('app.') or pn not in user_plugin_names:
                                                builtin_items.add((pn, item.get('type', ''), item.get('function', '')))
                                    if builtin_items:
                                        with ui.column().classes('w-full gap-1 max-h-[180px] overflow-y-auto pr-1'):
                                            for pn, ptype, pfunc in sorted(builtin_items):
                                                with ui.row().classes('items-center gap-2 w-full p-2 hover:bg-gray-50 rounded border-l-2 border-gray-300'):
                                                    ui.label('⚙️ 系统内置').classes('text-xs text-gray-500 bg-gray-100 px-1 rounded font-mono whitespace-nowrap')
                                                    ui.label(pn).classes('text-xs text-gray-600 font-mono')
                                                    ui.label(f'{ptype}:{pfunc}').classes('text-xs text-gray-400 font-mono ml-auto')
                                    else:
                                        ui.label('暂无系统内置实现').classes('text-xs text-gray-400 italic')
                                    ui.button('关闭', on_click=plugin_list_dialog.close).props('flat color=gray').classes('mt-4 self-end text-sm')
                            plugin_list_btn.on_click(plugin_list_dialog.open)

                        # 插件详情滚动容器（固定高度，内部滚动，不影响整个页面）
                        with ui.column().classes('w-full gap-4 overflow-y-auto px-3 py-4').style('max-height: 72vh; scroll-behavior: smooth;').props('id=plugin-detail-scroll') as plugin_detail_scroll:
                            if registry:
                                for module_name, info in registry.items():
                                    status = info['status']
                                    error = info.get('error')

                                    if status == 'loaded':
                                        status_color = 'positive'
                                        status_icon = 'check_circle'
                                        status_text = '已加载'
                                    else:
                                        status_color = 'negative'
                                        status_icon = 'error'
                                        status_text = '加载失败'

                                    # 插件友好名称（用于 data-plugin 属性和点击跳转）
                                    display_name = info.get('name', module_name.split('.')[-1])
                                    plugin_version = info.get('version', 'unknown')
                                    plugin_author = info.get('author', 'unknown')
                                    plugin_description = info.get('description', '')
                                    plugin_tags = info.get('tags', [])

                                    with ui.card().classes('w-full shadow-sm hover:shadow-md transition-shadow').props(f'data-plugin="{display_name}"'):
                                        with ui.column().classes('gap-3 p-4'):
                                            # 插件头部
                                            with ui.row().classes('items-center justify-between w-full'):
                                                with ui.row().classes('items-center gap-2'):
                                                    ui.icon(status_icon, size='sm').classes(f'text-{status_color}')
                                                    ui.label(display_name).classes('font-bold text-gray-800 text-lg')
                                                    ui.badge(f'v{plugin_version}', color='grey').props('outline')
                                                    ui.badge(status_text, color=status_color).props('outline')

                                                # 展开/收起配置按钮
                                                if module_name in all_configs and all_configs[module_name].get('schema'):
                                                    cfg_btn = ui.button('⚙️ 配置', icon='settings').props('outline color=primary size=sm')
                                                else:
                                                    cfg_btn = None

                                            # 插件元信息
                                            with ui.column().classes('gap-1'):
                                                ui.label(module_name).classes('text-xs text-gray-400 font-mono')
                                                if plugin_description:
                                                    ui.label(plugin_description).classes('text-sm text-gray-600')
                                                if plugin_author and plugin_author != 'unknown':
                                                    ui.label(f'👤 作者: {plugin_author}').classes('text-xs text-gray-400')
                                                if plugin_tags:
                                                    with ui.row().classes('gap-1 flex-wrap'):
                                                        for tag in plugin_tags:
                                                            ui.badge(tag, color='primary').props('outline').classes('text-xs')

                                            if error:
                                                ui.label(f'❌ 加载错误: {error}').classes('text-sm text-red-600')

                                            # 该插件注册的扩展点统计（从 hook_details 和 spi_details 中收集）
                                            plugin_hook_count = 0
                                            plugin_spi_count = 0
                                            for event, hooks in stats.get('hook_details', {}).items():
                                                plugin_hook_count += sum(1 for h in hooks if h['plugin'] == display_name)
                                            for stype, impls in stats.get('spi_details', {}).items():
                                                plugin_spi_count += sum(1 for s in impls if s['plugin'] == display_name)

                                            with ui.row().classes('gap-2 flex-wrap'):
                                                if plugin_hook_count > 0:
                                                    ui.badge(f'🔌 {plugin_hook_count} 个钩子', color='info').props('outline')
                                                if plugin_spi_count > 0:
                                                    ui.badge(f'⚙️ {plugin_spi_count} 个SPI', color='secondary').props('outline')
                                                if module_name in all_configs:
                                                    ui.badge('🔧 可配置', color='warning').props('outline')

                                            # 插件配置区域（默认隐藏，点击展开）
                                            if cfg_btn and module_name in all_configs:
                                                cfg_area = ui.column().classes('w-full gap-3 border-t pt-3')
                                                cfg_area.visible = False

                                                def toggle_cfg(area=cfg_area, btn=cfg_btn):
                                                    area.visible = not area.visible
                                                    btn.props(f'label={"收起配置" if area.visible else "⚙️ 配置"}')

                                                cfg_btn.on_click(lambda e, area=cfg_area, btn=cfg_btn: toggle_cfg(area, btn))

                                                with cfg_area:
                                                    schema = all_configs[module_name].get('schema', {})
                                                    try:
                                                        current_cfg = await get_plugin_config(module_name)
                                                    except Exception:
                                                        current_cfg = all_configs[module_name].get('default', {})

                                                    config_values = dict(current_cfg)

                                                    for field_key, field_def in schema.items():
                                                        field_type = field_def.get('type', 'string')
                                                        field_label = field_def.get('label', field_key)
                                                        field_help = field_def.get('help', '')
                                                        field_default = field_def.get('default', config_values.get(field_key))

                                                        with ui.row().classes('items-center gap-3 w-full'):
                                                            ui.label(field_label).classes('text-sm text-gray-600 w-36 shrink-0')
                                                            if field_type == 'boolean':
                                                                switch = ui.switch(value=bool(config_values.get(field_key, field_default)))
                                                                switch.on_value_change(lambda e, k=field_key: config_values.update({k: e.value}))
                                                            elif field_type == 'select':
                                                                options = field_def.get('options', [])
                                                                select = ui.select(options, value=config_values.get(field_key, field_default))
                                                                select.on_value_change(lambda e, k=field_key: config_values.update({k: e.value}))
                                                            elif field_type == 'number':
                                                                number = ui.number(value=config_values.get(field_key, field_default))
                                                                number.on_value_change(lambda e, k=field_key: config_values.update({k: e.value}))
                                                            elif field_type == 'textarea':
                                                                textarea = ui.textarea(value=str(config_values.get(field_key, field_default)))
                                                                textarea.on_value_change(lambda e, k=field_key: config_values.update({k: e.value}))
                                                            else:
                                                                text_input = ui.input(value=str(config_values.get(field_key, field_default)))
                                                                text_input.on_value_change(lambda e, k=field_key: config_values.update({k: e.value}))
                                                            if field_help:
                                                                ui.tooltip(field_help).classes('text-xs')

                                                    async def save_plugin_config(pn=module_name, cv=config_values):
                                                        try:
                                                            await set_plugin_config(pn, cv)
                                                            ui.notify(f'{pn} 配置已保存', type='positive')
                                                        except Exception as e:
                                                            ui.notify(f'保存失败: {e}', type='negative')

                                                    ui.button('💾 保存配置', on_click=save_plugin_config).props('color=primary')
                            else:
                                with ui.card().classes('w-full text-center p-12'):
                                    ui.icon('extension', size='4rem').classes('text-gray-400')
                                    ui.label('暂无配置插件').classes('text-xl text-gray-500 mt-4')
                                    ui.label('设置环境变量 WOOLGATE_PLUGINS 来启用插件').classes('text-sm text-gray-400 mt-2')

                # ═══ 配置说明 ═══
                with ui.card().classes('w-full bg-blue-50 border-l-4 border-blue-500'):
                    with ui.column().classes('gap-2 p-4'):
                        ui.label('💡 插件配置说明').classes('text-lg font-bold text-blue-800')
                        ui.label('插件通过环境变量 WOOLGATE_PLUGINS 配置，逗号分隔模块路径。例如：').classes('text-sm text-blue-700')
                        ui.code('WOOLGATE_PLUGINS=plugins.balance_monitor,my_company.audit_plugin').classes('text-xs bg-white p-2 rounded w-full')
                        ui.label('修改后需重启服务生效。插件 import 失败会被跳过，不影响启动。').classes('text-xs text-blue-600')

        await render_content()
