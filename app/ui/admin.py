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
from app.models.database import ModelAccount, SystemConfig, RequestLog, DomainPrototype, DomainModelMapping
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
    """获取所有账号列表"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelAccount).order_by(desc(ModelAccount.priority))
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
        ('⚙️ 系统配置', '/config', 'config'),
        ('🧠 管线策略', '/pipeline', 'pipeline'),
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
            
            # 账号列表
            if accounts:
                for acc in accounts:
                    # 提前提取所有需要的数据（避免在 UI 构建时访问 ORM 对象）
                    acc_id = acc.id
                    acc_vendor = acc.vendor
                    acc_model_name = acc.model_name
                    acc_priority = acc.priority
                    acc_is_enable = acc.is_enable
                    acc_total_prompt_tokens = acc.total_prompt_tokens or 0
                    acc_total_completion_tokens = acc.total_completion_tokens or 0
                    acc_base_url = acc.base_url
                    acc_extra_json = acc.extra_json
                    acc_balance_remaining = acc.balance_remaining
                    acc_balance_unit = acc.balance_unit
                    acc_balance_sync_date = acc.balance_sync_date
                    acc_daily_used_tokens = acc.daily_used_tokens or 0
                    acc_daily_used_currency = acc.daily_used_currency or 0
                    acc_total_used_currency = acc.total_used_currency or 0
                    acc_total_tokens = (acc.total_prompt_tokens or 0) + (acc.total_completion_tokens or 0)

                    # 统一余额口径：预计余额 = 初始额度 - 当日本地用量
                    if acc_balance_remaining is not None and acc_balance_unit:
                        if acc_balance_unit == 'token':
                            acc_daily_used = float(acc_daily_used_tokens)
                            acc_est_balance = acc_balance_remaining - acc_daily_used
                            init_text = f"{acc_balance_remaining:,.0f} tokens"
                            daily_text = f"{acc_daily_used:,.0f} tokens"
                            est_text = f"{acc_est_balance:,.0f} tokens"
                            quota_percent = (acc_est_balance / acc_balance_remaining * 100) if acc_balance_remaining > 0 else 0
                        else:
                            acc_daily_used = acc_daily_used_currency
                            acc_est_balance = acc_balance_remaining - acc_daily_used
                            init_text = f"¥{acc_balance_remaining:.2f}"
                            daily_text = f"¥{acc_daily_used:.2f}"
                            est_text = f"¥{max(acc_est_balance, 0):.2f}"
                            quota_percent = (acc_est_balance / acc_balance_remaining * 100) if acc_balance_remaining > 0 else 0
                    else:
                        quota_percent = 0
                    
                    # 解析 extra_json
                    actual_model = '未配置'
                    actual_model_class = 'text-xs text-orange-500'
                    if acc_extra_json:
                        try:
                            # SQLAlchemy 可能已经反序列化为 dict，不需要再 json.loads
                            if isinstance(acc_extra_json, dict):
                                extra_data = acc_extra_json
                            else:
                                extra_data = json.loads(str(acc_extra_json))
                            
                            if isinstance(extra_data, dict) and 'model' in extra_data:
                                actual_model = str(extra_data['model'])
                                actual_model_class = 'text-xs font-mono text-green-600 font-semibold'
                            else:
                                actual_model = 'JSON格式错误'
                                actual_model_class = 'text-xs text-red-500'
                        except Exception as e:
                            actual_model = f'解析错误: {type(e).__name__}'
                            actual_model_class = 'text-xs text-red-500'
                    
                    # 账号卡片
                    with ui.card().classes('w-full account-card shadow-md'):
                        with ui.row().classes('w-full items-start justify-between gap-4'):
                            # 左侧信息
                            with ui.column().classes('flex-1 gap-3'):
                                # 标题行
                                with ui.row().classes('items-center gap-3 flex-wrap'):
                                    ui.icon('business', size='sm').classes('text-purple-600')
                                    ui.label(f"{acc_vendor}").classes('text-xl font-bold text-gray-800')
                                    ui.label(f"模型: {acc_model_name}").classes('text-sm text-gray-600 bg-gray-100 px-2 py-1 rounded')
                                    ui.badge(f"优先级 {acc_priority}", color='blue')
                                    if acc_is_enable:
                                        ui.badge('✅ 启用', color='positive')
                                    else:
                                        ui.badge('❌ 停用', color='negative')
                                
                                # 统一余额展示：初始额度 + 当日用量 + 预计余额（或有初始额度）
                                if acc_balance_remaining is not None and acc_balance_unit:
                                    with ui.column().classes('w-full gap-1'):
                                        with ui.row().classes('items-center justify-between w-full'):
                                            ui.label(f"📊 初始额度: {init_text}").classes('text-sm text-gray-600')
                                            sync_info = f'（{acc_balance_sync_date} 同步）' if acc_balance_sync_date else ''
                                            ui.label(sync_info).classes('text-xs text-gray-400')
                                        with ui.row().classes('items-center justify-between w-full'):
                                            ui.label(f"📈 当日用量: {daily_text}").classes('text-sm text-gray-600')
                                            ui.label(f"预计余额: {est_text}").classes('text-sm font-bold text-blue-600')
                                        ui.linear_progress(quota_percent / 100).props('color=primary size=8px rounded')
                                else:
                                    # 无接口厂商：直接显示累计用量 + 当日用量
                                    with ui.column().classes('w-full gap-1'):
                                        with ui.row().classes('items-center justify-between w-full'):
                                            ui.label(f"📊 累计用量: {acc_total_tokens:,} tokens").classes('text-sm text-gray-600')
                                            ui.label(f"¥{acc_total_used_currency:.2f}").classes('text-sm font-mono text-gray-500')
                                        ui.label(f"📈 当日用量: {acc_daily_used_tokens:,} tokens / ¥{acc_daily_used_currency:.2f}").classes('text-sm text-gray-600')
                                
                                # 累计薅羊毛（token 计数，不计算金额）
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.icon('savings', size='sm').classes('text-red-500')
                                    ui.label(f"累计薅羊毛：输入token {acc_total_prompt_tokens / 1_000_000:.4f}百万；输出token {acc_total_completion_tokens / 1_000_000:.4f}百万").classes('text-sm font-semibold text-red-600')
                                
                                ui.separator()
                                
                                # Base URL
                                with ui.row().classes('items-center gap-2'):
                                    ui.label('🔗 API:').classes('text-xs font-bold text-gray-500')
                                    if acc_base_url:
                                        ui.label(str(acc_base_url)).classes('text-xs font-mono text-blue-600')
                                    else:
                                        ui.label('未配置').classes('text-xs text-orange-500 font-semibold')
                                
                                # 实际模型
                                with ui.row().classes('items-center gap-2'):
                                    ui.label('🤖 实际模型:').classes('text-xs font-bold text-gray-500')
                                    ui.label(actual_model).classes(actual_model_class)
                            
                            # 右侧操作按钮
                            with ui.column().classes('gap-2'):
                                # 启用/停用切换按钮
                                if acc_is_enable:
                                    ui.button('⏸ 停用', on_click=lambda aid=acc_id: toggle_account_enable(aid, False)).props('outline color=warning').classes('w-32')
                                else:
                                    ui.button('▶️ 启用', on_click=lambda aid=acc_id: toggle_account_enable(aid, True)).props('outline color=positive').classes('w-32')
                                # 自动获取：补 base_url/模型 + 拉取厂商真实余额
                                ui.button('🔄 自动获取', on_click=lambda aid=acc_id: auto_config_account(aid, fetch_balance=True)).props('color=orange').classes('w-32')
                                ui.button('✏️ 编辑', on_click=lambda aid=acc_id: show_account_dialog(account_id=aid)).props('outline color=primary').classes('w-32')
                                ui.button('🗑️ 删除', on_click=lambda aid=acc_id: show_delete_dialog(aid)).props('outline color=negative').classes('w-32')
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
        
        with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-6'):
            ui.label('⚙️ 全局系统配置').classes('text-3xl font-bold text-gray-800')
            ui.label('所有配置保存后立即生效，无需重启服务').classes('text-sm text-gray-500 -mt-4')
            
            # 获取当前配置
            config = await get_system_config()
            
            with ui.card().classes('w-full shadow-lg'):
                ui.label('额度耗尽策略').classes('text-xl font-bold text-gray-700 mb-3')
                quota_strategy = ui.select(
                    ['auto_switch_next', 'return_warn_error', 'allow_pay_quota'],
                    label='策略',
                    value=config.quota_exhaust_strategy
                ).classes('w-full')
                
                ui.separator().classes('my-6')
                
                ui.label('重试配置').classes('text-xl font-bold text-gray-700 mb-3')
                max_retry = ui.number('最大重试次数', value=config.max_retry_count, min=0, max=10).classes('w-full')
                cool_down = ui.number('故障冷却秒数', value=config.cool_down_seconds, min=0).classes('w-full')
                
                ui.separator().classes('my-6')
                
                ui.label('日志配置').classes('text-xl font-bold text-gray-700 mb-3')
                log_retention = ui.number('日志保留天数', value=config.log_retention_days, min=1).classes('w-full')

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

                ui.button('💾 保存配置', on_click=save).props('color=primary size=lg').classes('mt-6')


    @ui.page('/pipeline')
    async def pipeline_page():
        """管线策略配置页面（M1 三层策略管线）"""
        ui.page_title('管线策略 - WoolGate')

        # 顶部导航栏
        nav_header('pipeline')

        with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-6'):
            ui.label('🧠 管线策略配置').classes('text-3xl font-bold text-gray-800')
            ui.label('三层策略串行：模型路由（选羊）→ 账号调度（薅羊毛）→ 上下文管理，保存后立即生效').classes('text-sm text-gray-500 -mt-4')

            # 获取当前配置
            config = await get_system_config()

            # ── ① 模型路由（选羊）──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('① 模型路由策略（选羊）').classes('text-xl font-bold text-gray-700 mb-1')
                ui.label('根据用户请求语义，智能选择最适合的模型领域').classes('text-xs text-gray-500 mb-3')

                router_strategy = ui.select(
                    ['off', 'rules', 'vector', 'llm'],
                    label='路由策略',
                    value=getattr(config, 'router_strategy', 'off')
                ).classes('w-full')
                ui.label('off=不路由（默认） / rules=关键词匹配 / vector=向量相似度(企业) / llm=小模型分类(企业)').classes('text-xs text-gray-400 -mt-2')

            # ── ② 账号调度（薅羊毛）──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('② 账号调度策略（薅羊毛）').classes('text-xl font-bold text-gray-700 mb-1')
                ui.label('从可用账号池中选择具体账号，管理免费额度消耗顺序').classes('text-xs text-gray-500 mb-3')

                selector_strategy = ui.select(
                    ['pin', 'free-first', 'round-robin', 'sticky', 'failover', 'cost-first'],
                    label='调度策略',
                    value=getattr(config, 'selector_strategy', 'pin')
                ).classes('w-full')
                ui.label('pin=指定模型（默认） / free-first=免费额度优先 / round-robin=轮询 / sticky=会话粘性 / failover=主备(企业) / cost-first=成本最低(企业)').classes('text-xs text-gray-400 -mt-2')

            # ── ③ 上下文管理 ──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('③ 上下文管理策略').classes('text-xl font-bold text-gray-700 mb-1')
                ui.label('控制发送给上游的消息组装方式，平衡上下文完整性与 token 消耗').classes('text-xs text-gray-500 mb-3')

                context_strategy = ui.select(
                    ['passthrough', 'window', 'summary'],
                    label='上下文策略',
                    value=getattr(config, 'context_strategy', 'passthrough')
                ).classes('w-full')
                ui.label('passthrough=直传（默认） / window=滑动窗口 / summary=摘要压缩(企业)').classes('text-xs text-gray-400 -mt-2')

            # ── ④ 本地模型运行时 ──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('④ 本地模型运行时').classes('text-xl font-bold text-gray-700 mb-1')
                ui.label('Ollama 本地大模型运行时配置，用于本地分类、摘要、Embedding 等场景').classes('text-xs text-gray-500 mb-3')

                ollama_enabled = ui.checkbox('启用 Ollama 调度', value=config.ollama_enabled)
                ollama_url = ui.input('Ollama 地址', value=config.ollama_base_url).classes('w-full')
                ui.label('启用后，vendor=ollama 的账号可参与调度；关闭则全部跳过').classes('text-xs text-gray-400 -mt-2')

            # ── ⑤ 领域原型管理（向量路由用）──
            with ui.card().classes('w-full shadow-lg'):
                ui.label('⑤ 领域原型管理').classes('text-xl font-bold text-gray-700 mb-1')
                ui.label('向量路由的领域定义，每个领域有描述文本和预计算向量，路由时与用户消息算相似度').classes('text-xs text-gray-500 mb-3')

                # 操作按钮行
                with ui.row().classes('gap-2 mb-3'):
                    add_domain_btn = ui.button('+ 添加领域', icon='add').props('outline')
                    recompute_btn = ui.button('🔄 重算所有向量', icon='refresh').props('outline')

                # 领域列表容器（动态刷新）
                domain_list_container = ui.column().classes('w-full gap-2')

                async def refresh_domain_list():
                    """刷新领域列表"""
                    domain_list_container.clear()
                    async with AsyncSessionLocal() as session:
                        from app.services.domain_service import DomainService
                        svc = DomainService(session)
                        domains = await svc.list_domains()
                        if not domains:
                            ui.label('暂无领域，点击"添加领域"创建').classes('text-sm text-gray-400')
                            return
                        for d in domains:
                            mappings = await svc.list_mappings(d.id)
                            mapping_text = ', '.join([f"{m.model_name}(P{m.priority})" for m in mappings]) or '无模型映射'
                            vector_status = '✅ 已计算' if d.embedding_vector else '❌ 未计算'
                            with ui.row().classes('items-center w-full p-2 bg-gray-50 rounded gap-2'):
                                ui.label(f'**{d.name}**').classes('text-sm font-bold w-24')
                                ui.label(d.description[:40] + ('...' if len(d.description) > 40 else '')).classes('text-xs text-gray-600 flex-1')
                                ui.label(vector_status).classes('text-xs')
                                ui.label(f'模型: {mapping_text}').classes('text-xs text-gray-500')
                                ui.button(icon='delete', on_click=lambda did=d.id: delete_domain(did)).props('flat color=red size=sm')

                async def delete_domain(domain_id: int):
                    async with AsyncSessionLocal() as session:
                        from app.services.domain_service import DomainService
                        svc = DomainService(session)
                        await svc.delete_domain(domain_id)
                    ui.notify('领域已删除', type='positive')
                    await refresh_domain_list()

                async def add_domain_dialog():
                    """添加领域对话框"""
                    with ui.dialog() as dialog, ui.card():
                        ui.label('添加领域').classes('text-lg font-bold')
                        name_input = ui.input('领域名称（英文标识，如 code/creative）').classes('w-full')
                        desc_input = ui.textarea('领域描述（用于计算向量，越详细越好）').classes('w-full')
                        with ui.row().classes('justify-end gap-2'):
                            ui.button('取消', on_click=dialog.close).props('flat')
                            async def confirm():
                                if not name_input.value or not desc_input.value:
                                    ui.notify('请填写名称和描述', type='warning')
                                    return
                                async with AsyncSessionLocal() as session:
                                    from app.services.domain_service import DomainService
                                    from app.services.embedding import EmbeddingService
                                    from app.pipeline.config import PipelineConfig
                                    svc = DomainService(session)
                                    # 尝试计算向量（失败也保存）
                                    cfg = await PipelineConfig.load(session)
                                    embed_svc = EmbeddingService(cfg.router_config, db=session)
                                    await svc.create_domain(name_input.value.strip(), desc_input.value.strip(), embed_svc)
                                dialog.close()
                                ui.notify('领域已添加', type='positive')
                                await refresh_domain_list()
                            ui.button('确定', on_click=confirm).props('color=primary')
                    dialog.open()

                async def recompute_all():
                    """重算所有领域向量"""
                    recompute_btn.props('loading')
                    try:
                        async with AsyncSessionLocal() as session:
                            from app.services.domain_service import DomainService
                            from app.services.embedding import EmbeddingService
                            from app.pipeline.config import PipelineConfig
                            cfg = await PipelineConfig.load(session)
                            embed_svc = EmbeddingService(cfg.router_config, db=session)
                            svc = DomainService(session)
                            count = await svc.recompute_all_embeddings(embed_svc)
                        ui.notify(f'已重算 {count} 个领域向量', type='positive')
                        await refresh_domain_list()
                    except Exception as e:
                        ui.notify(f'重算失败: {e}', type='negative')
                    finally:
                        recompute_btn.props(remove='loading')

                add_domain_btn.on('click', add_domain_dialog)
                recompute_btn.on('click', recompute_all)

                # 初始加载
                await refresh_domain_list()

            # 保存按钮
            async def save_pipeline():
                config_data = {
                    'router_strategy': router_strategy.value,
                    'selector_strategy': selector_strategy.value,
                    'context_strategy': context_strategy.value,
                    'ollama_enabled': ollama_enabled.value,
                    'ollama_base_url': ollama_url.value,
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
                result = await session.execute(
                    select(RequestLog)
                    .order_by(desc(RequestLog.created_at))
                    .limit(50)
                )
                logs = result.scalars().all()
            
            # 统计信息（统一卡片模板：标题 + 大数字主值 + 小字副行，等高对齐）
            success_count = sum(1 for log in logs if log.status == 'success')
            failed_count = sum(1 for log in logs if log.status == 'failed')
            total_prompt = sum(log.prompt_tokens or 0 for log in logs)
            total_completion = sum(log.completion_tokens or 0 for log in logs)
            
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
                stat_card('📊', 'text-blue-600', '总请求数', str(len(logs)))
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
                    
                    # 状态颜色
                    if log_status == 'success':
                        status_color = 'positive'
                        status_icon = 'check_circle'
                    else:
                        status_color = 'negative'
                        status_icon = 'error'
                    
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
            ui.notify(f'已{"启用" if enable else "停用"} {account.vendor}', type='positive' if enable else 'warning')
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
                        'base_url': account.base_url or '',
                        'extra_model': extra_model,
                        'priority': account.priority if account.priority is not None else 50,
                        'is_enable': account.is_enable if account.is_enable is not None else True,
                        'balance_remaining': account.balance_remaining,
                        'balance_unit': account.balance_unit or 'currency',
                        'currency_rate': account.currency_rate or 0,
                    }

        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label('✏️ 编辑账号' if account_id else '➕ 新增账号').classes('text-2xl font-bold')

            vendor = ui.input('厂商名称', value=initial['vendor']).classes('w-full')
            api_key = ui.input('API Key', value=initial['api_key'], password=True, password_toggle_button=True).classes('w-full')
            model_name = ui.input('模型名称（路由匹配）', value=initial['model_name']).classes('w-full')
            base_url = ui.input('API Base URL', value=initial['base_url']).classes('w-full')

            # 实际模型名：可下拉选择（自动获取填充）也可手动输入，无需手写 JSON
            # 初始 options 必须包含当前值，否则空列表 + 非空 value 会抛 ValueError
            _extra_options = [initial['extra_model']] if initial['extra_model'] else []
            extra_model = ui.select(options=_extra_options, with_input=True, label='实际模型名（上游调用，自动获取可填充）', value=initial['extra_model']).classes('w-full')
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
                        extra_model.options = models
                        extra_model.update()
                        if extra_model.value not in models:
                            extra_model.value = models[0]
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

            ui.button('🔄 自动获取', on_click=auto_fetch).props('color=orange outline').classes('w-full')

            priority = ui.number('优先级', value=initial['priority'], min=0, max=100).classes('w-full')
            is_enable = ui.checkbox('启用', value=initial['is_enable'])

            ui.separator()

            balance_unit = ui.select(['token', 'currency'], label='额度单位', value=initial['balance_unit']).classes('w-full')
            balance_remaining = ui.number('初始额度（厂商余额自动同步；手动维护/充值请在此重置）', value=initial['balance_remaining'], min=0).classes('w-full')
            currency_rate = ui.number('厂商结算单价（元/1M token，currency 单位时用于估算金额消耗）', value=initial['currency_rate'], min=0).classes('w-full')

            async def save():
                try:
                    # 构造 extra_json：只存实际模型名（保留原 extra_json 其他键）
                    orig_extra = {}
                    if account_id:
                        async with AsyncSessionLocal() as _s:
                            _r = await _s.execute(select(ModelAccount).where(ModelAccount.id == account_id))
                            _acc = _r.scalar_one_or_none()
                            if _acc and isinstance(_acc.extra_json, dict):
                                orig_extra = dict(_acc.extra_json)
                    parsed_extra = dict(orig_extra)
                    if extra_model.value:
                        parsed_extra['model'] = extra_model.value.strip()

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

                    ui.notify('保存成功，正在刷新...', type='positive')
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
