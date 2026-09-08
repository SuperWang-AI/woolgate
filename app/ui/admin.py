"""
NiceGUI管理界面
提供网页端账号管理、配置、统计等功能
"""
from nicegui import ui, app
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import json

from app.models import AsyncSessionLocal
from app.models.database import ModelAccount, SystemConfig, RequestLog, ModelCatalog
from app.utils.encryption import encryption_service
from app.config import settings

# 默认市场行情价（2026年基准价）
DEFAULT_MARKET_PRICES = {
    "deepseek-v4-flash": (1.0, 2.0),
    "deepseek-v4-pro": (3.2, 6.4),
    "qwen3.7-max": (12.0, 36.0),
    "qwen3.7-plus": (2.0, 8.0),
    "qwen3.5-flash": (0.2, 2.0),
    "kimi-k2.6": (6.5, 27.0),
    "glm-5.2": (8.0, 28.0),
    "hunyuan-t1": (1.0, 4.0),
}


async def get_stats():
    """获取首页统计数据"""
    async with AsyncSessionLocal() as session:
        # 账号统计
        result = await session.execute(select(func.count(ModelAccount.id)))
        total_accounts = result.scalar() or 0
        
        result = await session.execute(
            select(func.count(ModelAccount.id))
            .where(ModelAccount.is_enable == True)
        )
        enabled_accounts = result.scalar() or 0
        
        # 今日请求量
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(func.count(RequestLog.id))
            .where(RequestLog.created_at >= today_start)
        )
        today_requests = result.scalar() or 0
        
        # 累计Token（输入/输出）
        result = await session.execute(
            select(func.sum(ModelAccount.total_prompt_tokens), func.sum(ModelAccount.total_completion_tokens))
        )
        row = result.one()
        total_prompt_tokens = row[0] or 0
        total_completion_tokens = row[1] or 0
        
        # 今日Token（输入/输出）
        result = await session.execute(
            select(func.sum(RequestLog.prompt_tokens), func.sum(RequestLog.completion_tokens))
            .where(RequestLog.created_at >= today_start)
        )
        row = result.one()
        today_prompt_tokens = row[0] or 0
        today_completion_tokens = row[1] or 0
        
        return {
            "total_accounts": total_accounts,
            "enabled_accounts": enabled_accounts,
            "today_requests": today_requests,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "today_prompt_tokens": today_prompt_tokens,
            "today_completion_tokens": today_completion_tokens,
        }


async def get_accounts():
    """获取所有账号列表（启用的排在前面）"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelAccount).order_by(desc(ModelAccount.is_enable), desc(ModelAccount.priority))
        )
        return result.scalars().all()


async def get_system_config():
    """获取系统配置"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
        config = result.scalar_one_or_none()
        if not config:
            config = SystemConfig(id=1)
            session.add(config)
            await session.commit()
        return config


async def save_system_config(config_data: dict):
    """保存系统配置"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
        config = result.scalar_one_or_none()
        
        if config:
            for key, value in config_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            await session.commit()
            return True
        return False


def create_ui():
    """创建UI"""
    
    # 添加自定义样式
    ui.add_head_html('''
        <style>
            .header-gradient {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .stat-card {
                transition: transform 0.2s, box-shadow 0.2s;
            }
            .stat-card:hover {
                transform: translateY(-4px);
                box-shadow: 0 12px 24px rgba(0,0,0,0.15);
            }
            .account-card {
                transition: all 0.2s;
                border-left: 4px solid #667eea;
            }
            .account-card:hover {
                box-shadow: 0 8px 16px rgba(0,0,0,0.1);
            }
        </style>
    ''')
    
    # 导航页面定义（label, path, key）
    NAV_PAGES = [
        ('🏠 首页', '/', 'home'),
        ('👥 账号管理', '/accounts', 'accounts'),
        ('🧠 模型能力', '/models', 'models'),
        ('⚙️ 系统配置', '/config', 'config'),
        ('🧩 管线策略', '/pipeline', 'pipeline'),
        ('📋 请求日志', '/logs', 'logs'),
    ]

    def nav_header(current: str):
        """顶部导航栏（tab 效果：当前页白色背景高亮，其他页透明）"""
        with ui.header().classes('header-gradient items-center justify-between px-6 shadow-lg'):
            with ui.row().classes('items-center gap-4'):
                ui.label('🐑').classes('text-4xl')
                ui.label('WoolGate').classes('text-2xl font-bold text-white')
            with ui.row().classes('gap-2'):
                for label, path, key in NAV_PAGES:
                    if key == current:
                        # 当前页：白色背景高亮 + 深色文字（内联样式强制覆盖，确保可读）
                        ui.button(label, on_click=lambda p=path: ui.navigate.to(p)) \
                            .props('no-caps') \
                            .style('background-color:#ffffff !important; color:#764ba2 !important; font-weight:700; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.18);')
                    else:
                        ui.button(label, on_click=lambda p=path: ui.navigate.to(p)) \
                            .props('flat no-caps text-color=white')

    @ui.page('/')
    async def index():
        """首页"""
        ui.page_title('WoolGate - AI 羊毛聚合网关')
        
        # 顶部导航栏
        nav_header('home')
        
        # 主内容区域
        with ui.column().classes('w-full max-w-7xl mx-auto p-6 gap-6'):
            # 欢迎标题
            ui.label('AI 羊毛聚合网关').classes('text-4xl font-bold text-gray-800')
            ui.label('智能调度多平台免费额度，自动切换账号').classes('text-lg text-gray-500 -mt-4')
            
            # 统计数据
            stats = await get_stats()
            
            ui.label('📊 实时统计').classes('text-2xl font-bold text-gray-800 mt-4')
            
            # 统一统计卡片模板：图标 + 标题 + 大数字主值 + 小字副行（支持多行），固定高度完全等高
            def stat_card(icon, icon_color, title, value, sub=None):
                with ui.card().classes('flex-1 stat-card shadow-lg').style('height:170px'):
                    with ui.column().classes('w-full items-center gap-1 justify-center').style('height:100%'):
                        ui.icon(icon, size='2.5rem').classes(f'text-{icon_color}')
                        ui.label(title).classes('text-gray-500 text-sm')
                        ui.label(value).classes('text-3xl font-bold').style('min-height:36px; display:flex; align-items:center; justify-content:center;')
                        if sub:
                            lines = sub if isinstance(sub, (list, tuple)) else [sub]
                            for line in lines:
                                ui.label(line).classes('text-xs text-gray-500 text-center').style('line-height:1.4')
            
            with ui.row().classes('w-full gap-4'):
                # 总账号数
                stat_card('account_circle', 'blue-500', '总账号数',
                          f"{stats['total_accounts']}",
                          f"✅ 启用: {stats['enabled_accounts']}")
                # 今日请求
                stat_card('analytics', 'purple-500', '今日请求',
                          f"{stats['today_requests']}",
                          "次")
                # 今日 Token
                today_total_m = (stats['today_prompt_tokens'] + stats['today_completion_tokens']) / 1_000_000
                stat_card('savings', 'orange-500', '今日 Token',
                          f"{today_total_m:.4f}M",
                          [f"输入 {stats['today_prompt_tokens'] / 1_000_000:.4f}M",
                           f"输出 {stats['today_completion_tokens'] / 1_000_000:.4f}M"])
                # 累计 Token
                total_total_m = (stats['total_prompt_tokens'] + stats['total_completion_tokens']) / 1_000_000
                stat_card('trending_up', 'red-500', '累计 Token',
                          f"{total_total_m:.4f}M",
                          [f"输入 {stats['total_prompt_tokens'] / 1_000_000:.4f}M",
                           f"输出 {stats['total_completion_tokens'] / 1_000_000:.4f}M"])
            
            # API 配置信息卡片
            ui.label('📡 API 配置信息').classes('text-2xl font-bold text-gray-800 mt-4')
            with ui.card().classes('w-full shadow-lg border-l-4 border-purple-500'):
                with ui.grid(columns=2).classes('w-full gap-4'):
                    # API Base URL
                    with ui.column().classes('gap-2'):
                        ui.label('API Base URL').classes('text-sm font-bold text-gray-600')
                        dify_base = f"http://localhost:8765/v1"
                        with ui.row().classes('items-center gap-2 bg-gray-50 p-3 rounded'):
                            ui.label(dify_base).classes('font-mono text-sm flex-1')
                            ui.button(icon='content_copy', on_click=lambda: [
                                ui.run_javascript(f'navigator.clipboard.writeText("{dify_base}")'),
                                ui.notify('已复制 API Base URL', type='positive')
                            ]).props('flat dense color=primary').tooltip('复制')
                    
                    # Authorization Token
                    with ui.column().classes('gap-2'):
                        ui.label('Authorization Token').classes('text-sm font-bold text-gray-600')
                        with ui.row().classes('items-center gap-2 bg-gray-50 p-3 rounded'):
                            ui.label(settings.GATEWAY_BEARER_TOKEN).classes('font-mono text-sm flex-1')
                            ui.button(icon='content_copy', on_click=lambda t=settings.GATEWAY_BEARER_TOKEN: [
                                ui.run_javascript(f'navigator.clipboard.writeText("{t}")'),
                                ui.notify('已复制 Token', type='positive')
                            ]).props('flat dense color=primary').tooltip('复制')
                
                ui.separator()
                
                # Dify 配置示例
                ui.label('🔧 Dify 配置示例').classes('text-lg font-bold text-gray-700 mt-4 mb-2')
                with ui.column().classes('gap-3 bg-blue-50 p-4 rounded'):
                    dify_base = f"http://localhost:8765/v1"
                    config_items = [
                        ('模型供应商', '自定义模型'),
                        ('模型名称', 'chat'),
                        ('模型类型', '文本生成 / LLM'),
                        ('API Base URL', dify_base),
                        ('API Key', settings.GATEWAY_BEARER_TOKEN),
                    ]
                    for label, value in config_items:
                        with ui.row().classes('items-center gap-2'):
                            ui.label(f'{label}:').classes('text-sm font-bold text-gray-600 w-32')
                            ui.label(value).classes('font-mono text-sm text-blue-700 flex-1')
                            ui.button(icon='content_copy', on_click=lambda v=value: [
                                ui.run_javascript(f'navigator.clipboard.writeText("{v}")'),
                                ui.notify(f'已复制 {label}', type='positive')
                            ]).props('flat dense size=sm color=primary').tooltip('复制')
            
            # 快速操作
            ui.label('⚡ 快速操作').classes('text-2xl font-bold text-gray-800 mt-4')
            with ui.row().classes('gap-3'):
                ui.button('➕ 新增账号', on_click=lambda: ui.navigate.to('/accounts')).props('color=primary size=lg')
                ui.button('⚙️ 系统配置', on_click=lambda: ui.navigate.to('/config')).props('color=secondary size=lg outline')
                ui.button('📋 查看日志', on_click=lambda: ui.navigate.to('/logs')).props('color=accent size=lg outline')
    
    
    @ui.page('/accounts')
    async def accounts_page():
        """账号管理页面"""
        ui.page_title('账号管理 - WoolGate')
        
        # 顶部导航栏
        nav_header('accounts')
        
        with ui.column().classes('w-full max-w-7xl mx-auto p-6 gap-6'):
            with ui.row().classes('items-center justify-between w-full'):
                ui.label('🎯 模型账号管理').classes('text-3xl font-bold text-gray-800')
                ui.button('➕ 新增账号', on_click=lambda: show_account_dialog()).props('color=primary size=lg')
            
            # 获取账号列表
            accounts = await get_accounts()
            
            # 查询所有模型的 display_name 映射
            model_display_map = {}
            async with AsyncSessionLocal() as session:
                catalog_result = await session.execute(select(ModelCatalog))
                for catalog in catalog_result.scalars().all():
                    model_display_map[catalog.model_name] = catalog.display_name or catalog.model_name
            
            # 按厂商分组，并查询每个厂商下的模型能力
            from collections import defaultdict
            vendor_groups = defaultdict(list)
            for acc in accounts:
                vendor_groups[acc.vendor].append(acc)
            
            # 建立 model_name -> account 的映射
            model_to_account = {a.model_name: a for a in accounts}
            
            # 查询每个厂商的模型能力（从ModelCatalog）
            vendor_models = {}
            async with AsyncSessionLocal() as session:
                for vendor in vendor_groups.keys():
                    cat_result = await session.execute(
                        select(ModelCatalog).where(ModelCatalog.vendor == vendor)
                    )
                    vendor_models[vendor] = cat_result.scalars().all()
            
            # 账号列表（按厂商分组显示，可折叠）
            if accounts:
                for vendor, vendor_accounts in vendor_groups.items():
                    models = vendor_models.get(vendor, [])
                    
                    # 厂商分组卡片（可折叠）
                    with ui.card().classes('w-full shadow-md'):
                        # 标题行（可点击展开/折叠）
                        with ui.row().classes('items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50') as header_row:
                            ui.icon('business', size='md').classes('text-purple-600')
                            ui.label(f'{vendor}').classes('text-lg font-bold text-gray-800')
                            ui.badge(f'{len(models)} 个模型', color='purple')
                            # 显示启用的模型数
                            active_count = sum(1 for m in models if m.is_active)
                            ui.badge(f'{active_count} 启用', color='positive')
                            # 折叠箭头
                            expand_icon = ui.icon('expand_more', size='md').classes('text-gray-400 ml-auto')
                        
                        # 可折叠内容区域
                        with ui.column().classes('w-full px-4 pb-4 gap-3') as content_area:
                            content_area.visible = False
                            
                            # 模型能力列表（显示全部模型，停用的置灰显示，便于恢复）
                            models_to_show = models
                            if models_to_show:
                                ui.label('📋 模型清单').classes('text-sm font-bold text-gray-600 mt-2')
                                for model in models_to_show:
                                    # 获取该模型对应的账号信息
                                    acc = model_to_account.get(model.model_name)
                                    acc_id = acc.id if acc else None
                                    acc_is_enable = acc.is_enable if acc else False
                                    acc_priority = acc.priority if acc else 0
                                    acc_total_prompt = acc.total_prompt_tokens or 0 if acc else 0
                                    acc_total_completion = acc.total_completion_tokens or 0 if acc else 0
                                    acc_balance = acc.balance_remaining if acc else None
                                    acc_balance_unit = acc.balance_unit if acc else None
                                    acc_daily_tokens = acc.daily_used_tokens or 0 if acc else 0
                                    acc_base_url = acc.base_url if acc else ''
                                    
                                    card_cls = 'w-full shadow-sm' + ('' if model.is_active else ' opacity-60')
                                    with ui.card().classes(card_cls):
                                        # 标题行
                                        with ui.row().classes('items-center gap-2 w-full'):
                                            ui.icon('smart_toy', size='sm').classes('text-blue-500')
                                            ui.label(model.display_name or model.model_name).classes('text-sm font-bold text-gray-700')
                                            ui.badge(model.model_type or 'chat', color='blue').classes('text-xs')
                                            ui.badge(f'优先级 {acc_priority}', color='grey').classes('text-xs')
                                            if acc_is_enable:
                                                ui.badge('✅ 启用', color='positive').classes('text-xs')
                                            else:
                                                ui.badge('❌ 停用', color='negative').classes('text-xs')
                                            ui.space()
                                            # 操作按钮
                                            if acc_id:
                                                if acc_is_enable:
                                                    ui.button('⏸ 停用', on_click=lambda aid=acc_id: toggle_account_enable(aid, False)).props('outline size=xs color=warning').classes('text-xs')
                                                else:
                                                    ui.button('▶️ 启用', on_click=lambda aid=acc_id: toggle_account_enable(aid, True)).props('outline size=xs color=positive').classes('text-xs')
                                                ui.button('✏️ 编辑', on_click=lambda aid=acc_id: show_account_dialog(account_id=aid)).props('outline size=xs color=primary').classes('text-xs')
                                                ui.button('🧠 能力', on_click=lambda m=model: show_model_capability_dialog(m.id)).props('outline size=xs color=purple').classes('text-xs')
                                        
                                        # 能力描述（截断显示）
                                        if model.capability_description:
                                            desc = model.capability_description[:80] + '...' if len(model.capability_description) > 80 else model.capability_description
                                            ui.label(desc).classes('text-xs text-gray-500 mt-1')
                                        
                                        # 用量统计
                                        with ui.row().classes('items-center gap-4 mt-2 flex-wrap'):
                                            ui.label(f'📊 累计: 输入{acc_total_prompt/1_000_000:.2f}M / 输出{acc_total_completion/1_000_000:.2f}M tokens').classes('text-xs text-gray-500')
                                            ui.label(f'📈 当日: {acc_daily_tokens:,} tokens').classes('text-xs text-gray-500')
                                            if acc_balance is not None and acc_balance_unit:
                                                if acc_balance_unit == 'token':
                                                    ui.label(f'💰 余额: {acc_balance:,.0f} tokens').classes('text-xs font-bold text-blue-600')
                                                else:
                                                    ui.label(f'💰 余额: ¥{acc_balance:.2f}').classes('text-xs font-bold text-blue-600')
                                            if acc_base_url:
                                                ui.label(f'🔗 {acc_base_url[:40]}...').classes('text-xs font-mono text-gray-400')
                    
                    # 点击标题行切换展开/折叠
                    async def toggle_content(area=content_area, icon=expand_icon):
                        area.visible = not area.visible
                        icon.props(f'name={"expand_more" if not area.visible else "expand_less"}')
                    header_row.on('click', toggle_content)
            else:
                with ui.card().classes('w-full text-center p-12'):
                    ui.icon('info', size='4rem').classes('text-gray-400')
                    ui.label('暂无账号').classes('text-xl text-gray-500 mt-4')
                    ui.label('点击右上角"新增账号"按钮添加第一个账号').classes('text-sm text-gray-400')
    
    
    @ui.page('/config')
    async def config_page():
        """系统配置页面"""
        ui.page_title('系统配置 - WoolGate')
        
        # 顶部导航栏
        nav_header('config')
        
        with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-4'):
            ui.label('⚙️ 全局系统配置').classes('text-3xl font-bold text-gray-800')
            ui.label('所有配置保存后立即生效，无需重启服务').classes('text-sm text-gray-500 -mt-3')

            # 获取当前配置
            config = await get_system_config()

            # 额度耗尽策略
            with ui.card().classes('w-full shadow-sm'):
                with ui.row().classes('items-center gap-3 w-full flex-wrap'):
                    ui.label('额度耗尽策略').classes('text-sm font-bold text-gray-600 w-32')
                    quota_strategy = ui.select(
                        ['auto_switch_next', 'return_warn_error', 'allow_pay_quota'],
                        value=config.quota_exhaust_strategy
                    ).classes('w-72')
                    ui.label('auto_switch_next=自动切下个账号 / return_warn_error=报错 / allow_pay_quota=允许扣费').classes('text-xs text-gray-400 flex-1')

            # 重试与日志
            with ui.card().classes('w-full shadow-sm'):
                with ui.row().classes('items-center gap-6 w-full flex-wrap'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label('最大重试次数').classes('text-sm text-gray-600')
                        max_retry = ui.number(value=config.max_retry_count, min=0, max=10).classes('w-28')
                    with ui.row().classes('items-center gap-2'):
                        ui.label('故障冷却(秒)').classes('text-sm text-gray-600')
                        cool_down = ui.number(value=config.cool_down_seconds, min=0).classes('w-28')
                    with ui.row().classes('items-center gap-2'):
                        ui.label('日志保留(天)').classes('text-sm text-gray-600')
                        log_retention = ui.number(value=config.log_retention_days, min=1).classes('w-28')

            # 保存按钮
            async def save():
                config_data = {
                    'quota_exhaust_strategy': quota_strategy.value,
                    'max_retry_count': int(max_retry.value),
                    'cool_down_seconds': int(cool_down.value),
                    'log_retention_days': int(log_retention.value),
                }
                success = await save_system_config(config_data)
                if success:
                    ui.notify('配置已保存', type='positive')
                else:
                    ui.notify('保存失败', type='negative')

            with ui.row().classes('justify-end w-full'):
                ui.button('💾 保存配置', on_click=save).props('color=primary')



    @ui.page('/pipeline')
    async def pipeline_page():
        """管线策略配置页面"""
        ui.page_title('管线策略 - WoolGate')

        # 顶部导航栏
        nav_header('pipeline')

        with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-6'):
            ui.label('🧩 管线策略配置').classes('text-3xl font-bold text-gray-800')
            ui.label('三层策略串行：模型路由 → 账号调度 → 上下文管理，保存后立即生效').classes('text-sm text-gray-500 -mt-4')

            # 获取当前配置
            config = await get_system_config()

            # ── ① 模型路由 ──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('① 模型路由策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('根据用户请求语义，智能选择最适合的模型').classes('text-xs text-gray-500 mb-3')

                router_strategy = ui.select(
                    ['off', 'vector', 'llm', 'hybrid'],
                    label='路由策略',
                    value=getattr(config, 'router_strategy', 'off')
                ).classes('w-72')
                ui.label('off=不路由 / vector=向量相似度 / llm=小模型分类 / hybrid=混合（向量高置信直接用，低置信升级LLM）').classes('text-xs text-gray-400 -mt-2 mb-3')

                # 加载当前 router_config
                from app.pipeline.config import PipelineConfig
                _pipeline_cfg = await PipelineConfig.load(AsyncSessionLocal())
                _router_cfg = _pipeline_cfg.router_config

                ui.label('Embedding 配置（vector/hybrid 策略用）').classes('text-sm font-bold text-gray-600 mt-2 mb-1')
                
                # 查询ModelCatalog中所有embedding类型的模型
                from app.models.database import ModelCatalog, ModelAccount
                async with AsyncSessionLocal() as _s:
                    _cat_result = await _s.execute(
                        select(ModelCatalog).where(ModelCatalog.model_type == 'embedding')
                    )
                    _embed_models = _cat_result.scalars().all()
                    # 查询所有账号用于显示
                    _acc_result = await _s.execute(select(ModelAccount))
                    _accounts = {a.id: a for a in _acc_result.scalars().all()}
                
                _embed_options = {0: '自动（选第一个embedding模型）'}
                for _m in _embed_models:
                    _acc = _accounts.get(_m.account_id)
                    _acc_name = _acc.vendor if _acc else '未知'
                    _embed_options[_m.id] = f"{_m.display_name or _m.model_name}（{_acc_name}）"
                
                embedding_model_id = ui.select(
                    options=_embed_options,
                    label='选择 Embedding 模型',
                    value=getattr(_router_cfg, 'embedding_model_id', 0) or 0,
                ).classes('w-72')
                if not _embed_models:
                    ui.label('⚠️ 暂无embedding模型，请先在账号管理中添加').classes('text-xs text-red-500 -mt-2 mb-3')
                else:
                    ui.label('选模型后自动使用其关联账号的API Key，无需单独配置').classes('text-xs text-gray-400 -mt-2 mb-3')

                ui.label('滞回阈值（防频繁切换）').classes('text-sm font-bold text-gray-600 mt-2 mb-1')
                with ui.row().classes('gap-2 w-full'):
                    threshold_high = ui.number(
                        '切入阈值（高于此值切换）', value=_router_cfg.threshold_high,
                        min=0.0, max=1.0, step=0.05
                    ).classes('w-48')
                    threshold_low = ui.number(
                        '保持阈值（低于此值才允许切走）', value=_router_cfg.threshold_low,
                        min=0.0, max=1.0, step=0.05
                    ).classes('w-56')

            # ── ② 账号调度 ──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('② 账号调度策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('从可用账号池中选择具体账号，管理免费额度消耗顺序').classes('text-xs text-gray-500 mb-3')

                selector_strategy = ui.select(
                    ['pin', 'free-first', 'round-robin', 'sticky', 'failover', 'cost-first'],
                    label='调度策略',
                    value=getattr(config, 'selector_strategy', 'pin')
                ).classes('w-72')
                ui.label('pin=指定模型（默认） / free-first=免费额度优先 / round-robin=轮询 / sticky=会话粘性 / failover=主备 / cost-first=成本最低').classes('text-xs text-gray-400 -mt-2')

            # ── ③ 上下文管理 ──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('③ 上下文管理策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('控制发送给上游的消息组装方式，平衡上下文完整性与 token 消耗').classes('text-xs text-gray-500 mb-3')

                context_strategy = ui.select(
                    ['passthrough', 'window', 'summary'],
                    label='上下文策略',
                    value=getattr(config, 'context_strategy', 'passthrough')
                ).classes('w-72')
                ui.label('passthrough=直传（默认） / window=滑动窗口 / summary=摘要压缩').classes('text-xs text-gray-400 -mt-2 mb-3')

                _context_cfg = _pipeline_cfg.context_config

                ui.label('滑动窗口参数（window 策略用）').classes('text-sm font-bold text-gray-600 mt-2 mb-1')
                window_turns = ui.number(
                    '保留最近 N 轮对话', value=_context_cfg.window_turns, min=1, max=100
                ).classes('w-48')

                ui.label('摘要模型配置（summary 策略用）').classes('text-sm font-bold text-gray-600 mt-3 mb-1')
                with ui.row().classes('gap-2 w-full'):
                    summary_provider = ui.select(
                        ['cloud', 'local'], label='摘要模型后端', value=_context_cfg.summary_provider
                    ).classes('flex-1')
                    summary_model = ui.input(
                        '摘要模型名', value=_context_cfg.summary_model
                    ).classes('flex-1')
                with ui.row().classes('gap-2 w-full'):
                    summary_trigger_turns = ui.number(
                        '触发阈值（轮数）', value=_context_cfg.summary_trigger_turns, min=1
                    ).classes('flex-1')
                    summary_trigger_tokens = ui.number(
                        '触发阈值（token）', value=_context_cfg.summary_trigger_tokens, min=100
                    ).classes('flex-1')
                summary_window_turns = ui.number(
                    '摘要后保留最近 N 轮原文', value=_context_cfg.summary_window_turns, min=0, max=20
                ).classes('w-48')
                ui.label('cloud=从账号池选该模型的启用账号 / local=调用 Ollama；跨模型切换时强制摘要').classes('text-xs text-gray-400 -mt-2')

            # ── ④ 本地模型运行时 ──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('④ 本地模型运行时（Ollama）').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('用于本地 Embedding、摘要等轻量任务，不参与主模型调度').classes('text-xs text-gray-500 mb-3')

                with ui.row().classes('items-center gap-3 w-full'):
                    ollama_enabled = ui.checkbox('启用 Ollama', value=config.ollama_enabled)
                    ollama_url = ui.input('Ollama 地址', value=config.ollama_base_url).classes('flex-1')
                ui.label('启用后，vendor=ollama 的账号可参与调度；关闭则全部跳过').classes('text-xs text-gray-400 -mt-2')

            # 保存按钮
            async def save_pipeline():
                # 组装 router_config_json
                router_config_json = {
                    'embedding_backend': 'cloud',
                    'embedding_model_id': int(embedding_model_id.value),
                    'threshold_high': float(threshold_high.value),
                    'threshold_low': float(threshold_low.value),
                }
                # 组装 context_config_json
                context_config_json = {
                    'window_turns': int(window_turns.value),
                    'summary_provider': summary_provider.value,
                    'summary_model': summary_model.value,
                    'summary_trigger_turns': int(summary_trigger_turns.value),
                    'summary_trigger_tokens': int(summary_trigger_tokens.value),
                    'summary_window_turns': int(summary_window_turns.value),
                }
                config_data = {
                    'router_strategy': router_strategy.value,
                    'selector_strategy': selector_strategy.value,
                    'context_strategy': context_strategy.value,
                    'ollama_enabled': ollama_enabled.value,
                    'ollama_base_url': ollama_url.value,
                    'router_config_json': router_config_json,
                    'context_config_json': context_config_json,
                }
                success = await save_system_config(config_data)
                if success:
                    # 使 PipelineConfig 缓存失效，下次请求加载新配置
                    from app.pipeline.config import PipelineConfig
                    PipelineConfig.invalidate_cache()
                    ui.notify('管线策略已保存，立即生效', type='positive')
                else:
                    ui.notify('保存失败', type='negative')

            ui.button('💾 保存策略', on_click=save_pipeline).props('color=primary size=lg').classes('mt-2')


    @ui.page('/models')
    async def models_page():
        """模型能力管理页面（M4 智能路由核心配置）"""
        ui.page_title('模型能力 - WoolGate')
        nav_header('models')

        with ui.column().classes('w-full max-w-6xl mx-auto p-6 gap-6'):
            ui.label('🧠 模型能力管理').classes('text-3xl font-bold text-gray-800')
            ui.label('LLM 智能路由的核心配置：每个模型的能力描述、典型示例和能力向量。新增账号后自动同步，可手动微调').classes('text-sm text-gray-500 -mt-4')

            # 操作按钮行
            with ui.row().classes('gap-2'):
                sync_btn = ui.button('同步账号模型', icon='refresh').props('outline')
                recompute_btn = ui.button('重算所有能力向量', icon='refresh').props('outline')

            # 模型列表容器
            model_list_container = ui.column().classes('w-full gap-3')

            async def refresh_model_list():
                """刷新模型能力清单"""
                model_list_container.clear()
                async with AsyncSessionLocal() as session:
                    from app.services.model_catalog_service import ModelCatalogService
                    svc = ModelCatalogService(session)
                    models = await svc.list_active_models()
                    if not models:
                        ui.label('暂无模型，点击"同步账号模型"从启用账号同步').classes('text-sm text-gray-400 p-4')
                        return
                    for m in models:
                        vector_status = '✅ 已计算' if m.embedding_vector else '❌ 未计算'
                        examples_count = len(m.examples) if m.examples else 0
                        with ui.card().classes('w-full shadow-md'):
                            with ui.row().classes('items-center w-full gap-3'):
                                display_name = m.display_name or m.model_name
                                ui.label(display_name).classes('text-lg font-bold w-40')
                                ui.label(f'[{m.vendor}]').classes('text-xs text-gray-500 w-24')
                                ui.label((m.capability_description or '')[:60] + ('...' if len(m.capability_description or '') > 60 else '')).classes('text-sm text-gray-600 flex-1')
                                ui.label(f'示例: {examples_count}条').classes('text-xs text-gray-500')
                                ui.label(vector_status).classes('text-xs')
                                edit_btn = ui.button('编辑', icon='edit').props('outline size=sm')

                            # 编辑对话框
                            def make_edit_dialog(model_id, model_name, vendor, cap_desc, examples_json):
                                with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
                                    ui.label(f'✏️ 编辑模型能力：{model_name}').classes('text-xl font-bold')
                                    ui.label(f'厂商：{vendor}').classes('text-sm text-gray-500 -mt-2')

                                    cap_input = ui.textarea('能力描述', value=cap_desc or '').classes('w-full').props('rows=3')
                                    examples_text = ui.textarea(
                                        '典型用户请求示例（每行一条，用于计算能力向量）',
                                        value='\n'.join(examples_json) if examples_json else ''
                                    ).classes('w-full').props('rows=8')
                                    ui.label('示例越多越口语化，向量匹配越精准。建议每个模型10-15条').classes('text-xs text-gray-400 -mt-2')

                                    async def save_model():
                                        try:
                                            examples_list = [line.strip() for line in examples_text.value.split('\n') if line.strip()]
                                            async with AsyncSessionLocal() as s:
                                                from app.services.model_catalog_service import ModelCatalogService
                                                svc2 = ModelCatalogService(s)
                                                result = await s.execute(select(ModelCatalog).where(ModelCatalog.id == model_id))
                                                model = result.scalar_one_or_none()
                                                if model:
                                                    model.capability_description = cap_input.value
                                                    model.examples = examples_list
                                                    await s.commit()
                                            ui.notify('已保存，正在重算能力向量...', type='positive')
                                            dialog.close()
                                            # 重算该模型向量
                                            async with AsyncSessionLocal() as s:
                                                from app.services.model_catalog_service import ModelCatalogService
                                                from app.services.embedding import EmbeddingService
                                                from app.pipeline.config import PipelineConfig
                                                cfg = await PipelineConfig.load(s)
                                                embed_svc = EmbeddingService(cfg.router_config, db=s)
                                                svc3 = ModelCatalogService(s)
                                                await svc3.recompute_all_embeddings(embed_svc)
                                            ui.notify('能力向量已更新', type='positive')
                                            await refresh_model_list()
                                        except Exception as e:
                                            ui.notify(f'保存失败: {e}', type='negative')

                                    with ui.row().classes('w-full justify-end gap-2 mt-4'):
                                        ui.button('取消', on_click=dialog.close).props('flat')
                                        ui.button('💾 保存并重算向量', on_click=save_model).props('color=primary')
                                return dialog

                            edit_dialog = make_edit_dialog(m.id, m.display_name or m.model_name, m.vendor, m.capability_description, m.examples)
                            edit_btn.on('click', edit_dialog.open)

            async def sync_models():
                """从启用账号同步模型到目录"""
                async with AsyncSessionLocal() as session:
                    from app.services.model_catalog_service import ModelCatalogService
                    svc = ModelCatalogService(session)
                    result = await session.execute(
                        select(ModelAccount).where(ModelAccount.is_enable == True)  # noqa: E712
                    )
                    accounts = result.scalars().all()
                    for account in accounts:
                        await svc.ensure_model(account.model_name, account.vendor)
                ui.notify(f'已同步 {len(accounts)} 个模型', type='positive')
                await refresh_model_list()

            async def recompute_all():
                """重算所有模型能力向量"""
                recompute_btn.props('loading')
                try:
                    async with AsyncSessionLocal() as session:
                        from app.services.model_catalog_service import ModelCatalogService
                        from app.services.embedding import EmbeddingService
                        from app.pipeline.config import PipelineConfig
                        cfg = await PipelineConfig.load(session)
                        embed_svc = EmbeddingService(cfg.router_config, db=session)
                        svc = ModelCatalogService(session)
                        count = await svc.recompute_all_embeddings(embed_svc)
                    ui.notify(f'已重算 {count} 个模型能力向量', type='positive')
                    await refresh_model_list()
                except Exception as e:
                    ui.notify(f'重算失败: {e}', type='negative')
                finally:
                    recompute_btn.props(remove='loading')

            sync_btn.on('click', sync_models)
            recompute_btn.on('click', recompute_all)

            # 初始加载
            await refresh_model_list()


    @ui.page('/logs')
    async def logs_page():
        """请求日志页面"""
        ui.page_title('请求日志 - WoolGate')
        
        # 顶部导航栏
        nav_header('logs')
        
        with ui.column().classes('w-full max-w-7xl mx-auto p-6 gap-4'):
            with ui.row().classes('items-center justify-between w-full'):
                ui.label('📋 请求日志').classes('text-3xl font-bold text-gray-800')
                ui.button('🔄 刷新', on_click=lambda: ui.run_javascript('window.location.reload()')).props('outline color=primary')
            
            # 获取最近 50 条日志
            async with AsyncSessionLocal() as session:
                # 查询统计数据（全部）
                from sqlalchemy import func
                total_result = await session.execute(select(func.count(RequestLog.id)))
                total_count = total_result.scalar() or 0
                
                success_result = await session.execute(select(func.count(RequestLog.id)).where(RequestLog.status == 'success'))
                success_count = success_result.scalar() or 0
                
                failed_result = await session.execute(select(func.count(RequestLog.id)).where(RequestLog.status == 'failed'))
                failed_count = failed_result.scalar() or 0
                
                token_result = await session.execute(
                    select(func.coalesce(func.sum(RequestLog.prompt_tokens), 0), 
                           func.coalesce(func.sum(RequestLog.completion_tokens), 0))
                )
                total_prompt, total_completion = token_result.first()
                
                # 查询最近50条用于显示
                result = await session.execute(
                    select(RequestLog)
                    .order_by(desc(RequestLog.created_at))
                    .limit(50)
                )
                logs = result.scalars().all()
            
            def stat_card(icon, icon_color, title, value, sub=None):
                with ui.card().classes('flex-1').style('height:120px'):
                    with ui.column().classes('w-full items-center gap-1 justify-center').style('height:100%'):
                        ui.label(f'{icon} {title}').classes('text-sm text-gray-600')
                        ui.label(value).classes('text-3xl font-bold').style('min-height:36px; display:flex; align-items:center; justify-content:center;')
                        if sub:
                            lines = sub if isinstance(sub, (list, tuple)) else [sub]
                            for line in lines:
                                ui.label(line).classes('text-xs text-gray-500 text-center').style('line-height:1.4')
            
            with ui.row().classes('w-full gap-3'):
                stat_card('📊', 'text-blue-600', '总请求数', str(total_count))
                stat_card('✅', 'text-green-600', '成功', str(success_count))
                stat_card('❌', 'text-red-600', '失败', str(failed_count))
                stat_card('🐑', 'text-orange-600', '累计Token',
                          f"{total_prompt + total_completion:,}",
                          [f'输入 {total_prompt:,}', f'输出 {total_completion:,}'])
            
            # 日志列表
            if logs:
                for log in logs:
                    # 提取数据
                    log_vendor = log.vendor or '未知'
                    log_model = log.model_name or '未知'
                    log_status = log.status
                    log_created = log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '未知'
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
                        'switch_retry': ('🔄 切换重试', 'warning'),
                        'stream_interrupted': ('✂️ 输出中断', 'negative'),
                        'followup': ('💬 继续追问', 'positive'),
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
                                    ui.label(f'📝 输入: {log_prompt_tokens:,}').classes('text-gray-600')
                                    ui.label(f'📝 输出: {log_completion_tokens:,}').classes('text-gray-600')
                                    ui.label(f'📊 总计: {log_total_tokens:,}').classes('text-gray-600 font-bold')
                                    ui.label(f'⏱️ {log_response_time}ms').classes('text-gray-600')
                                
                                # 错误信息
                                if log_error:
                                    ui.separator().classes('my-1')
                                    with ui.row().classes('items-start gap-2'):
                                        ui.icon('warning', size='sm').classes('text-red-500')
                                        ui.label(str(log_error)).classes('text-sm text-red-600 flex-1')
            else:
                with ui.card().classes('w-full text-center p-12'):
                    ui.icon('inbox', size='4rem').classes('text-gray-400')
                    ui.label('暂无日志记录').classes('text-xl text-gray-500 mt-4')


async def sync_model_to_catalog(account, session):
    """同步账号模型到能力目录并计算向量，返回 (model_name, is_new)"""
    from app.services.model_catalog_service import ModelCatalogService
    from app.services.embedding import EmbeddingService
    from app.pipeline.config import PipelineConfig
    
    svc = ModelCatalogService(session)
    catalog = await svc.ensure_model(account.model_name, account.vendor)
    is_new = catalog.examples is None or len(catalog.examples) == 0
    
    # 新模型设置默认示例
    if is_new:
        default_examples = [
            '你好，今天天气怎么样', '帮我写一封请假邮件', '1+1等于几',
            '推荐一本好看的小说', '今天吃什么好呢', '帮我翻译这句话成英文',
            '给孩子讲个睡前故事', '微信怎么改密码', '周末去哪里玩比较好',
            '帮我总结一下这段文字', '电脑开不了机怎么办', '给我几个减肥的建议',
            '怎么提高工作效率', '推荐几部科幻电影', '帮我写个朋友圈文案',
        ]
        catalog.examples = default_examples
        if not catalog.capability_description:
            catalog.capability_description = f'{account.vendor}大模型，通用对话能力'
        await session.commit()
    
    # 计算向量（多示例平均）
    cfg = await PipelineConfig.load(session)
    embed_svc = EmbeddingService(cfg.router_config, db=session)
    if catalog.examples:
        vectors = []
        for example in catalog.examples:
            vec = await embed_svc.embed(example)
            if vec:
                vectors.append(vec)
        if vectors:
            dim = len(vectors[0])
            avg_vector = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
            catalog.embedding_vector = avg_vector
    elif catalog.capability_description:
        vec = await embed_svc.embed(catalog.capability_description)
        if vec:
            catalog.embedding_vector = vec
    await session.commit()
    
    return catalog.display_name or catalog.model_name, is_new


def toggle_account_enable(account_id: int, enable: bool):
    """启用/停用账号"""
    async def toggle():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelAccount).where(ModelAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
            if not account:
                ui.notify('账号不存在', type='negative')
                return
            account.is_enable = enable
            # 重新启用时清除冷却状态，避免残留故障冷却
            if enable:
                account.cool_down_until = None
            await session.commit()
            
            if enable:
                # 启用时自动同步模型并计算向量
                try:
                    model_display, is_new = await sync_model_to_catalog(account, session)
                    if is_new:
                        ui.notify(f'已启用 {account.vendor}，新增模型 {model_display} 并计算能力向量', type='positive')
                    else:
                        ui.notify(f'已启用 {account.vendor}，模型 {model_display} 能力向量已更新', type='positive')
                except Exception as e:
                    ui.notify(f'已启用 {account.vendor}，但模型同步失败: {e}', type='warning')
            else:
                # 停用账号时，检查该模型是否还有其他启用账号
                from app.services.model_catalog_service import ModelCatalogService
                result = await session.execute(
                    select(ModelAccount).where(
                        ModelAccount.model_name == account.model_name,
                        ModelAccount.is_enable == True  # noqa: E712
                    )
                )
                remaining = result.scalars().all()
                if not remaining:
                    # 没有其他启用账号，标记模型为不可用
                    catalog_result = await session.execute(
                        select(ModelCatalog).where(ModelCatalog.model_name == account.model_name)
                    )
                    catalog = catalog_result.scalar_one_or_none()
                    if catalog and catalog.is_active:
                        catalog.is_active = False
                        await session.commit()
                        ui.notify(f'已停用 {account.vendor}，模型 {account.model_name} 无其他启用账号，已从路由池移除', type='warning')
                    else:
                        ui.notify(f'已停用 {account.vendor}', type='warning')
                else:
                    ui.notify(f'已停用 {account.vendor}（模型 {account.model_name} 仍有 {len(remaining)} 个启用账号）', type='warning')
            # 刷新页面
            ui.run_javascript('setTimeout(() => window.location.reload(), 600)')
    ui.timer(0.01, toggle, once=True)


def show_account_dialog(account_id: Optional[int] = None):
    """显示账号编辑对话框"""
    async def show():
        # 加载初始数据用于回填（只读，session 用完即关，不跨回调持有）
        initial = {
            'vendor': '',
            'api_key': '',
            'model_name': 'chat',
            'endpoint_id': '',
            'base_url': '',
            'extra_model': '',
            'priority': 50,
            'is_enable': True,
            'balance_remaining': None,
            'balance_unit': 'currency',
            'currency_rate': 0,
        }
        if account_id:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ModelAccount).where(ModelAccount.id == account_id)
                )
                account = result.scalar_one_or_none()
                if account:
                    api_key_plain = ''
                    if account.api_key_encrypted:
                        try:
                            api_key_plain = encryption_service.decrypt(account.api_key_encrypted)
                        except Exception:
                            api_key_plain = ''
                    extra_model = ''
                    if account.extra_json:
                        try:
                            if isinstance(account.extra_json, dict):
                                extra_model = str(account.extra_json.get('model', ''))
                            else:
                                extra_model = str(json.loads(account.extra_json).get('model', ''))
                        except Exception:
                            extra_model = ''
                    initial = {
                        'vendor': account.vendor or '',
                        'api_key': api_key_plain,
                        'model_name': account.model_name or 'chat',
                        'endpoint_id': account.endpoint_id or '',
                        'base_url': account.base_url or '',
                        'extra_model': extra_model,
                        'priority': account.priority if account.priority is not None else 50,
                        'is_enable': account.is_enable if account.is_enable is not None else True,
                        'balance_remaining': account.balance_remaining,
                        'balance_unit': account.balance_unit or 'currency',
                        'currency_rate': account.currency_rate or 0,
                    }

        with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl'):
            ui.label('✏️ 编辑账号' if account_id else '➕ 新增账号').classes('text-xl font-bold')

            with ui.row().classes('gap-4 w-full'):
                vendor = ui.input('厂商名称', value=initial['vendor']).classes('flex-1')
                api_key = ui.input('API Key', value=initial['api_key'], password=True, password_toggle_button=True).classes('flex-1')
            with ui.row().classes('gap-4 w-full'):
                model_name = ui.input('模型名称（用于显示和路由匹配）', value=initial['model_name']).classes('flex-1')
                endpoint_id = ui.input('Endpoint ID（豆包/火山引擎需要，可留空）', value=initial['endpoint_id']).classes('flex-1')
            base_url = ui.input('API Base URL', value=initial['base_url']).classes('w-full')

            # 实际模型名已由 model_name/endpoint_id 决定，不再提供独立字段（避免写入 extra_json.model 污染调用）
            balance_info_label = ui.label('💰 厂商余额: 未获取').classes('text-sm text-gray-600')

            async def auto_fetch():
                """自动获取：补 base_url、拉可用模型列表、拉厂商真实余额，实时填入表单"""
                try:
                    from app.services.balance import fetch_balance, fetch_models
                    if not vendor.value:
                        ui.notify('请先填写厂商名称', type='warning')
                        return
                    if not api_key.value:
                        ui.notify('请先填写 API Key', type='warning')
                        return
                    ui.notify('正在自动获取...', type='info')
                    # 构造临时账号对象（仅用于探测）
                    tmp = ModelAccount(
                        vendor=vendor.value,
                        api_key_encrypted=encryption_service.encrypt(api_key.value),
                        base_url=base_url.value or None,
                    )
                    # 1. 拉模型列表
                    models = await fetch_models(tmp)
                    if models:
                        ui.notify(f'发现 {len(models)} 个可用模型', type='info')
                    # 2. 拉余额
                    unit, bal = await fetch_balance(tmp)
                    balance_info_label.set_text(f'💰 厂商余额: {bal:.2f}（{unit}）')
                    balance_unit.value = unit  # 额度单位跟随厂商余额单位
                    # 3. 补 base_url（用默认映射）
                    if not base_url.value:
                        from app.services.llm_client import LLMClient
                        guess = LLMClient()._get_api_url(tmp)
                        if guess:
                            base_url.value = guess
                    ui.notify(f'✅ 已获取余额: {unit} {bal}，模型 {len(models)} 个', type='positive')
                except Exception as e:
                    ui.notify(f'自动获取失败: {str(e)[:120]}', type='negative')

            with ui.row().classes('items-center gap-3 w-full'):
                ui.button('🔄 自动获取', on_click=auto_fetch).props('color=orange outline').classes('w-44')
                balance_info_label.classes('text-sm text-gray-600 flex-1')

            with ui.row().classes('items-center gap-4 w-full'):
                priority = ui.number('优先级', value=initial['priority'], min=0, max=100).classes('w-40')
                is_enable = ui.checkbox('启用', value=initial['is_enable'])

            ui.separator()

            with ui.row().classes('gap-4 w-full items-center'):
                balance_unit = ui.select(['token', 'currency'], label='额度单位', value=initial['balance_unit']).classes('w-44')
                balance_remaining = ui.number('初始额度（厂商余额自动同步；手动维护/充值请在此重置）', value=initial['balance_remaining'], min=0).classes('flex-1')
            currency_rate = ui.number('厂商结算单价（元/1M token，currency 单位时用于估算金额消耗）', value=initial['currency_rate'], min=0).classes('w-full')

            async def save():
                try:
                    # 保留原 extra_json 其他键（不再写 model，模型由 model_name/endpoint_id 决定）
                    orig_extra = {}
                    if account_id:
                        async with AsyncSessionLocal() as _s:
                            _r = await _s.execute(select(ModelAccount).where(ModelAccount.id == account_id))
                            _acc = _r.scalar_one_or_none()
                            if _acc and isinstance(_acc.extra_json, dict):
                                orig_extra = dict(_acc.extra_json)
                    parsed_extra = dict(orig_extra)
                    parsed_extra.pop('model', None)

                    # 独立打开新 session 写库，避免复用已关闭的旧 session
                    async with AsyncSessionLocal() as session:
                        if account_id:
                            # 编辑：重新加载账号并更新
                            result = await session.execute(
                                select(ModelAccount).where(ModelAccount.id == account_id)
                            )
                            account = result.scalar_one_or_none()
                            if not account:
                                ui.notify('账号不存在', type='negative')
                                return
                            account.vendor = vendor.value
                            if api_key.value:
                                account.api_key_encrypted = encryption_service.encrypt(api_key.value)
                            account.model_name = model_name.value
                            account.endpoint_id = endpoint_id.value if endpoint_id.value else None
                            account.base_url = base_url.value
                            if parsed_extra:
                                account.extra_json = parsed_extra
                            account.priority = int(priority.value)
                            account.is_enable = is_enable.value
                            account.balance_unit = balance_unit.value
                            if balance_remaining.value is not None:
                                account.balance_remaining = float(balance_remaining.value)
                            account.currency_rate = float(currency_rate.value or 0)
                        else:
                            # 新增
                            new_account = ModelAccount(
                                vendor=vendor.value,
                                api_key_encrypted=encryption_service.encrypt(api_key.value) if api_key.value else '',
                                model_name=model_name.value,
                                endpoint_id=endpoint_id.value if endpoint_id.value else None,
                                base_url=base_url.value,
                                extra_json=parsed_extra,
                                priority=int(priority.value),
                                is_enable=is_enable.value,
                                balance_unit=balance_unit.value,
                                balance_remaining=float(balance_remaining.value) if balance_remaining.value is not None else None,
                                currency_rate=float(currency_rate.value or 0),
                            )
                            session.add(new_account)

                        await session.commit()
                        
                        # 保存后如果账号启用，自动同步模型并计算向量
                        saved_account = account if account_id else new_account
                        if saved_account.is_enable:
                            try:
                                model_display, is_new = await sync_model_to_catalog(saved_account, session)
                                sync_msg = f'，模型 {model_display} 已同步并计算向量'
                            except Exception as sync_err:
                                sync_msg = f'，但模型同步失败: {sync_err}'
                        else:
                            sync_msg = ''

                    ui.notify(f'保存成功{sync_msg}，正在刷新...', type='positive')
                    dialog.close()
                    # 刷新页面
                    ui.run_javascript('window.location.reload()')
                except Exception as e:
                    ui.notify(f'保存失败: {str(e)}', type='negative')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('取消', on_click=dialog.close).props('flat')
                ui.button('💾 保存', on_click=save).props('color=primary')

        dialog.open()

    ui.timer(0.01, show, once=True)


def show_model_capability_dialog(model_id: int):
    """显示模型能力详情对话框"""
    async def show():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelCatalog).where(ModelCatalog.id == model_id)
            )
            model = result.scalar_one_or_none()
            if not model:
                ui.notify('模型不存在', type='negative')
                return
            
            # 提前提取数据
            model_name = model.model_name
            display_name = model.display_name or model.model_name
            model_type = model.model_type or 'chat'
            vendor = model.vendor
            capability_description = model.capability_description or ''
            examples = model.examples or []
            is_active = model.is_active
        
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label(f'🧠 模型能力详情 - {display_name}').classes('text-2xl font-bold')
            ui.label(f'厂商: {vendor} | 类型: {model_type}').classes('text-sm text-gray-500')
            
            ui.separator()
            
            # 能力描述
            ui.label('能力描述').classes('text-sm font-bold text-gray-600')
            desc_input = ui.textarea(
                value=capability_description,
                placeholder='描述这个模型擅长什么，用于智能路由...'
            ).classes('w-full h-32')
            
            # 示例列表
            ui.label(f'典型请求示例（{len(examples)} 条，用于计算能力向量）').classes('text-sm font-bold text-gray-600 mt-2')
            examples_text = '\n'.join(examples) if examples else ''
            examples_input = ui.textarea(
                value=examples_text,
                placeholder='每行一条示例请求...'
            ).classes('w-full h-40 font-mono text-xs')
            
            # 启用状态
            is_active_checkbox = ui.checkbox('启用此模型', value=is_active)
            
            ui.separator()
            
            with ui.row().classes('gap-2 justify-end'):
                ui.button('取消', on_click=dialog.close).props('outline')
                
                async def save():
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(ModelCatalog).where(ModelCatalog.id == model_id)
                        )
                        m = result.scalar_one_or_none()
                        if m:
                            m.capability_description = desc_input.value
                            # 解析示例（每行一条）
                            new_examples = [line.strip() for line in examples_input.value.split('\n') if line.strip()]
                            m.examples = new_examples
                            m.is_active = is_active_checkbox.value
                            await session.commit()
                            ui.notify('模型能力已保存', type='positive')
                            dialog.close()
                            # 刷新页面
                            ui.navigate.to('/admin/accounts')
                
                ui.button('💾 保存', on_click=save).props('color=primary')
        dialog.open()
    
    ui.timer(0.01, show, once=True)


def auto_config_account(account_id: int, fetch_balance: bool = False):
    """自动配置账号（补 base_url/模型；fetch_balance=True 时同时拉取厂商真实余额）"""
    async def config():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelAccount).where(ModelAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
            if not account:
                ui.notify('账号不存在', type='negative')
                return
            
            # 根据厂商名称自动配置
            vendor_lower = account.vendor.lower()
            config_map = {
                '智谱': {
                    'base_url': 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
                    'model': 'glm-4-flash'
                },
                '百度': {
                    'base_url': 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions',
                    'model': 'ernie-speed-128k'
                },
                '月之暗面': {
                    'base_url': 'https://api.moonshot.cn/v1/chat/completions',
                    'model': 'moonshot-v1-8k'
                },
                'moonshot': {
                    'base_url': 'https://api.moonshot.cn/v1/chat/completions',
                    'model': 'moonshot-v1-8k'
                },
                'kimi': {
                    'base_url': 'https://api.moonshot.cn/v1/chat/completions',
                    'model': 'moonshot-v1-8k'
                },
                '阿里百炼': {
                    'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                    'model': 'qwen-plus'
                },
                '阿里': {
                    'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                    'model': 'qwen-plus'
                },
                '通义': {
                    'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                    'model': 'qwen-plus'
                },
                'qwen': {
                    'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                    'model': 'qwen-plus'
                },
                'deepseek': {
                    'base_url': 'https://api.deepseek.com/v1/chat/completions',
                    'model': 'deepseek-chat'
                },
                '深度求索': {
                    'base_url': 'https://api.deepseek.com/v1/chat/completions',
                    'model': 'deepseek-chat'
                },
                '硅基流动': {
                    'base_url': 'https://api.siliconflow.cn/v1/chat/completions',
                    'model': 'Qwen/Qwen2.5-7B-Instruct'
                },
                'siliconflow': {
                    'base_url': 'https://api.siliconflow.cn/v1/chat/completions',
                    'model': 'Qwen/Qwen2.5-7B-Instruct'
                },
                'openai': {
                    'base_url': 'https://api.openai.com/v1/chat/completions',
                    'model': 'gpt-3.5-turbo'
                },
                '豆包': {
                    'base_url': 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
                    'model': 'doubao-lite-4k'
                },
                'doubao': {
                    'base_url': 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
                    'model': 'doubao-lite-4k'
                },
            }
            
            # 查找匹配的配置
            config = None
            for key, value in config_map.items():
                if key in vendor_lower:
                    config = value
                    break
            
            if not config:
                ui.notify(f'未找到 "{account.vendor}" 的自动配置，请手动编辑', type='warning')
                return
            
            # 更新账号
            if not account.base_url:
                account.base_url = config['base_url']
            if not account.extra_json:
                account.extra_json = {'model': config['model']}
            
            # 拉取厂商真实余额（自动获取）
            balance_info = ''
            if fetch_balance:
                try:
                    from app.services.balance import fetch_balance, get_today_str
                    unit, bal = await fetch_balance(account)
                    account.balance_remaining = bal
                    account.balance_unit = unit
                    account.balance_sync_date = get_today_str()
                    balance_info = f"\n余额: {unit} {bal}"
                except Exception as e:
                    balance_info = f"\n余额获取失败: {str(e)[:80]}"
            
            await session.commit()
            
            ui.notify(f"✅ 已自动获取 {account.vendor}\nBase URL: {config['base_url']}\n模型: {config['model']}{balance_info}", type='positive')
            # 刷新页面
            ui.run_javascript('setTimeout(() => window.location.reload(), 1200)')
    
    ui.timer(0.01, config, once=True)


def show_delete_dialog(account_id: int):
    """显示删除确认对话框"""
    async def show():
        with ui.dialog() as dialog, ui.card():
            ui.label('⚠️ 确认删除').classes('text-xl font-bold text-red-600')
            ui.label('此操作不可恢复，确定要删除这个账号吗？').classes('text-gray-600')
            
            async def confirm_delete():
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(ModelAccount).where(ModelAccount.id == account_id)
                    )
                    acc = result.scalar_one_or_none()
                    if acc:
                        await session.delete(acc)
                        await session.commit()
                        ui.notify('账号已删除，正在刷新...', type='positive')
                        dialog.close()
                        # 刷新页面
                        ui.run_javascript('window.location.reload()')
            
            with ui.row().classes('mt-4 gap-2'):
                ui.button('取消', on_click=dialog.close).props('flat')
                ui.button('🗑️ 确认删除', on_click=confirm_delete).props('color=negative')
        
    
        dialog.open()
    ui.timer(0.01, show, once=True)


def init_ui(fastapi_app):
    """初始化NiceGUI并挂载到FastAPI"""
    create_ui()
    ui.run_with(
        fastapi_app,
        mount_path='/admin',
        storage_secret='woolgate-ui-secret-key-2026'
    )
