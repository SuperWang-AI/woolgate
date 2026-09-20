"""
NiceGUI管理界面
提供网页端账号管理、配置、统计等功能
"""
from nicegui import ui, app
from fastapi import Request
from sqlalchemy import select, func, desc, case
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncio
import json

from app.models import AsyncSessionLocal
from app.models.database import ModelAccount, SystemConfig, RequestLog, ModelCatalog
from app.utils.encryption import encryption_service
from app.config import settings
import html as _html
import urllib.parse as _up
from pathlib import Path

# 数据库时间统一以 UTC 存储，展示层转换为本地时区（Asia/Shanghai）
CN_TZ = timezone(timedelta(hours=8))

def local_fmt(dt):
    """UTC naive datetime → 本地时区展示字符串"""
    if not dt:
        return '未知'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')

def today_start_utc():
    """本地今天 00:00 对应的 UTC 时间（naive），用于按本地日统计"""
    local_midnight = datetime.now(CN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)

# 默认厂商图标兜底（找不到原厂图标时显示「AI」字母图标）
AI_FALLBACK = "data:image/svg+xml," + _up.quote(
    "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64'>"
    "<rect width='64' height='64' rx='14' fill='#7C6FF0'/>"
    "<text x='32' y='43' font-size='28' font-weight='700' fill='#fff' text-anchor='middle' "
    "font-family='Arial,Helvetica,sans-serif'>AI</text></svg>"
)

def vendor_icon_html(icon, cls='w-8 h-8 rounded object-contain'):
    """渲染厂商图标：有原厂 URL 用 img，加载失败/为空回退默认 AI 图标"""
    src = _html.escape((icon or '').strip(), quote=True)
    if not src:
        src = AI_FALLBACK
        return f"<img src='{src}' class='{cls}' alt='AI'>"
    return f"<img src='{src}' class='{cls}' alt='AI' loading='lazy' onerror=\"this.onerror=null;this.src='{AI_FALLBACK}'\">"

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
        today_start = today_start_utc()
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

        # 今日实际成本（省钱统计）
        result = await session.execute(
            select(func.sum(RequestLog.actual_cost))
            .where(RequestLog.created_at >= today_start)
        )
        today_cost = result.scalar() or 0

        # 今日免费模型请求数（actual_cost=0 视为免费）
        result = await session.execute(
            select(func.count(RequestLog.id))
            .where(RequestLog.created_at >= today_start)
            .where(RequestLog.actual_cost == 0)
        )
        today_free_requests = result.scalar() or 0

        # 累计实际成本
        result = await session.execute(
            select(func.sum(RequestLog.actual_cost))
        )
        total_cost = result.scalar() or 0

        # 累计总请求数
        result = await session.execute(
            select(func.count(RequestLog.id))
        )
        total_requests_all = result.scalar() or 0

        # 累计免费模型请求数
        result = await session.execute(
            select(func.count(RequestLog.id))
            .where(RequestLog.actual_cost == 0)
        )
        total_free_requests = result.scalar() or 0

        # ── P5 分类学习：分类准确率统计 ──
        # 总成功率（成功请求 / 总请求）
        result = await session.execute(
            select(func.count(RequestLog.id))
            .where(RequestLog.status == "success")
        )
        total_success = result.scalar() or 0
        overall_success_rate = (total_success / total_requests_all * 100) if total_requests_all > 0 else 0

        # 总降级率（降级请求 / 总请求）
        result = await session.execute(
            select(func.count(RequestLog.id))
            .where(RequestLog.degraded == True)
        )
        total_degraded = result.scalar() or 0
        overall_degrade_rate = (total_degraded / total_requests_all * 100) if total_requests_all > 0 else 0

        # 各路由模型成功率（P5 核心指标）
        result = await session.execute(
            select(
                RequestLog.routed_model,
                func.count(RequestLog.id).label("total"),
                func.sum(case((RequestLog.status == "success", 1), else_=0)).label("success"),
            )
            .where(RequestLog.routed_model.isnot(None))
            .group_by(RequestLog.routed_model)
        )
        domain_stats = []
        for row in result.all():
            rate = (row.success / row.total * 100) if row.total > 0 else 0
            domain_stats.append({
                "domain": row.routed_model,
                "total": row.total,
                "success": row.success,
                "rate": round(rate, 1),
            })
        # 按成功率升序排（最差的在前面，优先优化）
        domain_stats.sort(key=lambda x: x["rate"])

        return {
            "total_accounts": total_accounts,
            "enabled_accounts": enabled_accounts,
            "today_requests": today_requests,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "today_prompt_tokens": today_prompt_tokens,
            "today_completion_tokens": today_completion_tokens,
            "today_cost": today_cost,
            "today_free_requests": today_free_requests,
            "total_cost": total_cost,
            "total_requests_all": total_requests_all,
            "total_free_requests": total_free_requests,
            "overall_success_rate": round(overall_success_rate, 1),
            "overall_degrade_rate": round(overall_degrade_rate, 1),
            "domain_stats": domain_stats,
        }


async def get_accounts():
    """获取所有账号列表（启用的排在前面）"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelAccount).order_by(desc(ModelAccount.is_enable), desc(ModelAccount.id))
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


# ── A2 启动意图引导：3 问 → 推荐策略模板 ──
# v2.1（09-11 重设计）：
# 1) 使用方式：个人自用省钱 / 团队企业私有化部署 —— 突出各自核心价值（免费薅羊毛 / 数据不出域）
# 2) 省钱方式：免费云端模型优先 / 本地模型优先 —— 智能均衡（LLM 判题+上下文压缩）是默认常开的底座，不参与选择
# 3) 已有资源：本地大模型就绪 / 已有厂商 API Key / 都还没有 —— 资源盘点+指引，完成统一走免费向导
ONBOARD_ANSWERS_CN = {
    "way": {"personal": "个人自用省钱", "team": "企业私有化部署"},
    "saving": {"free": "免费模型优先", "local": "本地模型优先"},
    "resource": {"local": "本地大模型就绪", "key": "已有API Key", "none": "都还没有"},
}

def build_onboard_data(answers: dict):
    """
    A2 引导映射 v2.1（纯函数，便于测试）：3 个回答 → 推荐策略配置数据。

    设计原则（消灭用户侧配置，贴合省钱机制）：
    - 路由统一 hybrid（智能路由：向量快速路径 + LLM 兜底），LLM 智能判题 + 上下文压缩默认开启
    - 选号：个人 → 免费额度优先；企业 → 成本优先（付费为主）
    - 省钱方式：免费云端模型优先 → 摘要压缩走云端免费模型（glm-4-flash）；
                本地模型优先 → 开启 Ollama，判题/压缩/简单问答走本地（零成本、数据不出域）
    - 已有资源：本地大模型就绪 → 顺带开启 Ollama 调度；否则不强制。完成引导后统一跳转免费向导（向导回显/新增/本地首个卡片）

    Returns:
        (config_data, profile_name)
    """
    way = answers.get("way", "personal")
    saving = answers.get("saving", "free")
    resource = answers.get("resource", "none")

    router = "hybrid"
    selector = "free-first" if way == "personal" else "cost-first"

    if saving == "local":
        context = "summary"
        context_config = {
            "summary_provider": "local",
            "summary_trigger_turns": 20,
            "summary_trigger_tokens": 4000,
            "summary_window_turns": 3,
        }
    else:
        context = "summary"
        context_config = {
            "summary_provider": "cloud",
            "summary_model": "glm-4-flash",
            "summary_trigger_turns": 20,
            "summary_trigger_tokens": 4000,
            "summary_window_turns": 3,
        }

    data = {
        "router_strategy": router,
        "router_config_json": {"threshold_high": 0.65, "threshold_low": 0.55},
        "selector_strategy": selector,
        "context_strategy": context,
        "context_config_json": context_config,
        "onboarded": True,
    }
    if saving == "local" or resource == "local":
        data["ollama_enabled"] = True

    profile_name = "·".join([
        ONBOARD_ANSWERS_CN["way"].get(way, "个人自用省钱"),
        ONBOARD_ANSWERS_CN["saving"].get(saving, "免费模型优先"),
        ONBOARD_ANSWERS_CN["resource"].get(resource, "都还没有"),
    ])
    data["onboard_profile"] = profile_name
    return data, profile_name


async def apply_onboard_profile(answers: dict):
    """
    A2 启动意图引导：根据 3 个回答自动套用推荐策略模板。

    Returns:
        (success, profile_name)
    """
    data, profile_name = build_onboard_data(answers)
    ok = await save_system_config(data)
    if ok:
        # 使管线配置缓存失效，新策略立即生效
        from app.pipeline.config import PipelineConfig
        PipelineConfig.invalidate_cache()
    return ok, profile_name


def create_ui():
    """创建UI"""
    print(f"[DEBUG] create_ui() 被调用")

    # 插件系统 v2：UI 扩展点注册表
    from app.extensions.sdk import (
        page_registry, nav_registry, component_registry, config_registry,
        UI_HOOK_DASHBOARD_WIDGETS, UI_HOOK_ACCOUNT_CARD_FOOTER,
        UI_HOOK_LOG_DETAIL_EXTRA, UI_HOOK_CONFIG_PAGE_EXTRA,
    )

    # 导航页面定义（label, path, key）
    NAV_PAGES = [
        ('首页', '/', 'home'),
        ('🆓 免费向导', '/wizard', 'wizard'),
        ('账号管理', '/accounts', 'accounts'),
        ('系统配置', '/config', 'config'),
        ('管线策略', '/pipeline', 'pipeline'),
        ('请求日志', '/logs', 'logs'),
        ('插件管理', '/plugins', 'plugins'),
    ]

    def page_head():
        """全局 head：品牌图标 + 全局样式"""
        ui.colors(primary='#667eea', secondary='#764ba2')
        ui.add_head_html('''
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E🐑%3C/text%3E%3C/svg%3E">
<script>document.querySelectorAll('link[rel="shortcut icon"]').forEach(function(l){l.remove()})</script>
<style>
.header-gradient { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.stat-card { transition: transform 0.2s, box-shadow 0.2s; }
.stat-card:hover { transform: translateY(-4px); box-shadow: 0 12px 24px rgba(0,0,0,0.15); }
.account-card { transition: all 0.2s; border-left: 4px solid #667eea; }
.account-card:hover { box-shadow: 0 8px 16px rgba(0,0,0,0.1); }
.q-card { border-radius: 10px; }
body { font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Segoe UI', Roboto, sans-serif; }
</style>
''')

    def nav_header(current: str):
        """独立页面顶部导航（vendors 等保留整页跳转）"""
        page_head()
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
                # 插件注册的导航项
                for nav_item in nav_registry.list():
                    plugin_key = f"plugin_{nav_item['route'].strip('/').replace('/', '_')}"
                    if plugin_key == current:
                        ui.button(nav_item['label'], on_click=lambda p=nav_item['route']: ui.navigate.to('/admin' + p)) \
                            .props('no-caps') \
                            .style('background-color:#ffffff !important; color:#764ba2 !important; font-weight:700; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.18);')
                    else:
                        ui.button(nav_item['label'], on_click=lambda p=nav_item['route']: ui.navigate.to('/admin' + p)) \
                            .props('flat no-caps text-color=white')

    # SPA 路由映射：路由路径 ↔ tab key
    PATH_TO_KEY = {'/': 'home', '/wizard': 'wizard', '/accounts': 'accounts', '/config': 'config', '/pipeline': 'pipeline', '/logs': 'logs', '/plugins': 'plugins'}
    KEY_TO_PATH = {v: k for k, v in PATH_TO_KEY.items()}

    def nav_tabs(active_key: str):
        """SPA 顶部导航 tabs：点击仅前端切换面板，无整页刷新"""
        page_head()
        with ui.header().classes('header-gradient items-center justify-between px-6 shadow-lg'):
            with ui.row().classes('items-center gap-4'):
                ui.label('🐑').classes('text-4xl')
                ui.label('WoolGate').classes('text-2xl font-bold text-white')
            with ui.tabs().props('dense active-color=white indicator-color=white text-color=white').classes('gap-1') as tabs:
                for label, path, key in NAV_PAGES:
                    ui.tab(name=key, label=label)
                # 插件注册的导航项
                for nav_item in nav_registry.list():
                    plugin_key = f"plugin_{nav_item['route'].strip('/').replace('/', '_')}"
                    ui.tab(name=plugin_key, label=nav_item['label'])
        return tabs

    async def build_spa(active_key: str, request: Optional[Request] = None):
        """SPA 根：导航 tabs + 内容面板，导航切换零刷新（URL 用 history.replaceState 同步，刷新后仍停留当前页）"""
        ui.page_title('WoolGate AI 聚合网关')
        tabs = nav_tabs(active_key)

        def sync_url(e):
            path = KEY_TO_PATH.get(e.value, '/')
            ui.run_javascript(f"history.replaceState(null, '', '/admin{path}')")

        tabs.on_value_change(sync_url)

        with ui.tab_panels(tabs, value=active_key).classes('w-full'):
            with ui.tab_panel('home'):
                await home_view(request)
            with ui.tab_panel('wizard'):
                await wizard_view()
            with ui.tab_panel('accounts'):
                await accounts_view()
            with ui.tab_panel('config'):
                await config_view()
            with ui.tab_panel('pipeline'):
                await pipeline_view()
            with ui.tab_panel('logs'):
                await logs_view()
            with ui.tab_panel('plugins'):
                await plugins_view()

    @ui.page('/')
    async def index(request: Request):
        """首页（SPA）"""
        await build_spa('home', request)

    async def home_view(request: Optional[Request] = None):
        """首页视图（SPA tab 面板内容）——未完成 A2 启动引导时先展示引导，完成后显示仪表盘"""
        @ui.refreshable
        async def render():
            if await _needs_onboard(request):
                await _render_onboard(on_done=render.refresh)
            else:
                await _render_dashboard()
        await render()

    async def _needs_onboard(request: Optional[Request] = None) -> bool:
        """A2 引导触发条件：未完成引导 且（全新安装无账号 或 URL 带 ?onboard=1 强制预览）；
        预览模式仅在尚未完成引导时生效——应用成功后即使 URL 仍带 onboard=1 也进入仪表盘"""
        preview = bool(request and request.query_params.get('onboard') == '1')
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

    async def _render_onboard(on_done):
        """A2 启动引导面板：3 个问题 → 自动应用推荐策略模板（无整页刷新）"""
        step_idx = {"v": 0}
        answers: dict = {}
        steps = [
            ("使用方式", "你主要怎么使用 WoolGate？",
             [("personal", "个人自用省钱（免费薅羊毛，几乎零成本）"),
              ("team", "团队/企业私有化部署（数据不出域，预算可控）")]),
            ("省钱方式", "智能路由（LLM 智能判题 + 上下文压缩）系统默认开启，为你省 token。你希望优先用哪种资源来跑这些省钱动作？",
             [("free", "免费云端模型（推荐：免费额度足够，无需额外配置）"),
              ("local", "本地模型（Ollama：数据不出域，判题/压缩/简单问答零成本）")]),
            ("已有资源", "你手头已有哪些资源？",
             [("local", "本地大模型（Ollama）已就绪"),
              ("key", "已有厂商 API Key"),
              ("none", "都还没有")]),
        ]
        step_keys = ["way", "saving", "resource"]

        with ui.column().classes('w-full items-center p-6'):
            with ui.card().classes('w-full shadow-lg border-t-4 border-green-500 p-6').style('max-width:760px'):
                with ui.row().classes('items-center gap-3 w-full'):
                    ui.label('🐑 WoolGate AI 聚合网关').classes('text-2xl font-bold text-gray-800')
                ui.label('回答 3 个问题，自动为你配好路由与调度策略——你只管用，配置交给系统。').classes('text-sm text-gray-500 mt-1')

                @ui.refreshable
                async def render_step():
                    # 步骤指示器（带序号，随步骤切换刷新底色）
                    with ui.row().classes('gap-2 mt-3 w-full'):
                        for i, sl in enumerate([s[0] for s in steps]):
                            active = i == step_idx['v']
                            done = i < step_idx['v']
                            ui.label(f'{i + 1}. {sl}').classes(
                                'text-sm px-3 py-1 rounded-full '
                                + ('bg-green-100 text-green-700 font-bold' if active
                                   else ('text-gray-400' if done else 'text-gray-500'))
                            )
                    ui.separator().classes('my-4')
                    title, desc, opts = steps[step_idx['v']]
                    ui.label(title).classes('text-xl font-bold text-gray-800')
                    ui.label(desc).classes('text-sm text-gray-500 mb-3')
                    choices = {k: v for k, v in opts}
                    key = step_keys[step_idx['v']]
                    ui.radio(
                        choices,
                        value=answers.get(key),
                        on_change=lambda e, k=key: answers.update({k: e.value}),
                    ).props('stack').classes('gap-1')

                    async def next_step():
                        if step_idx['v'] < 2:
                            await go(1)
                        else:
                            await finish()

                    with ui.row().classes('w-full justify-between mt-6'):
                        if step_idx['v'] > 0:
                            ui.button('← 上一步', on_click=lambda: go(-1)).props('outline color=grey')
                        if step_idx['v'] < 2:
                            ui.button('下一步 →', on_click=next_step).props('color=primary size=lg')
                        else:
                            ui.button('完成并应用', on_click=finish).props('color=green size=lg')

                async def go(delta: int):
                    step_idx['v'] += delta
                    await render_step.refresh()

                async def finish():
                    ok, profile = await apply_onboard_profile(answers)
                    if ok:
                        ui.notify(f'已应用智能配置：{profile}。可在「管线策略」页随时微调。', type='positive', position='top')
                        # 统一走免费向导：本地大模型→向导首个卡片；已有 Key→向导粘贴/回显新增；都没有→向导领取免费额度
                        ui.navigate.to('/wizard')
                    else:
                        ui.notify('应用失败，请重试', type='negative')

                await render_step()

    async def _render_dashboard():
        """首页仪表盘（引导完成后显示）"""
        
        # 主内容区域
        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            # 欢迎标题
            ui.label('AI 羊毛聚合网关').classes('text-4xl font-bold text-gray-800')
            ui.label('智能调度多平台免费额度，自动切换账号').classes('text-lg text-gray-500 -mt-4')
            
            # 统计数据
            stats = await get_stats()
            
            ui.label('实时统计').classes('text-2xl font-bold text-gray-800 mt-4')
            
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

            # 省钱统计卡片
            ui.label('省钱统计').classes('text-2xl font-bold text-gray-800 mt-4')
            with ui.row().classes('w-full gap-4'):
                # 今日花费
                stat_card('payments', 'green-500', '今日花费',
                          f"¥{stats['today_cost']:.4f}",
                          "实际成本")
                # 今日免费占比
                today_free_pct = (stats['today_free_requests'] / stats['today_requests'] * 100) if stats['today_requests'] > 0 else 0
                stat_card('card_giftcard', 'teal-500', '今日免费占比',
                          f"{today_free_pct:.1f}%",
                          [f"{stats['today_free_requests']} 次免费", "走免费模型"])
                # 累计花费
                stat_card('account_balance_wallet', 'blue-500', '累计花费',
                          f"¥{stats['total_cost']:.4f}",
                          "实际成本")
                # 累计免费占比
                total_free_pct = (stats['total_free_requests'] / stats['total_requests_all'] * 100) if stats['total_requests_all'] > 0 else 0
                stat_card('emoji_events', 'yellow-500', '累计免费占比',
                          f"{total_free_pct:.1f}%",
                          [f"{stats['total_free_requests']} 次免费", "走免费模型"])
            
            # ── P5 分类学习统计 ──
            if stats['total_requests_all'] > 0:
                ui.label('分类学习统计').classes('text-2xl font-bold text-gray-800 mt-4')
                with ui.row().classes('w-full gap-4'):
                    stat_card('check_circle', 'green-500', '总成功率',
                              f"{stats['overall_success_rate']:.1f}%",
                              f"{stats['total_requests_all']} 次请求")
                    stat_card('warning', 'orange-500', '降级率',
                              f"{stats['overall_degrade_rate']:.1f}%",
                              "分类失败时兜底")
                
                # 各模型路由成功率
                if stats.get('domain_stats'):
                    with ui.card().classes('w-full shadow-lg mt-2'):
                        ui.label('各模型路由成功率（按成功率升序）').classes('text-sm font-bold text-gray-600 mb-2')
                        _cols = [
                            {'name': 'domain', 'label': '模型', 'field': 'domain'},
                            {'name': 'total', 'label': '总请求', 'field': 'total'},
                            {'name': 'success', 'label': '成功', 'field': 'success'},
                            {'name': 'rate', 'label': '成功率', 'field': 'rate'},
                        ]
                        ui.table(columns=_cols, rows=stats['domain_stats']).classes('w-full').props('dense flat')
            
            # API 配置信息卡片
            ui.label('API 配置信息').classes('text-2xl font-bold text-gray-800 mt-4')
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
                ui.label('Dify 配置示例').classes('text-lg font-bold text-gray-700 mt-4 mb-2')
                _dash_cfg = await get_system_config()
                _entry_name = getattr(_dash_cfg, 'virtual_entry_name', 'woolgate') or 'woolgate'
                with ui.column().classes('gap-3 bg-blue-50 p-4 rounded'):
                    config_items = [
                        ('模型供应商', 'OpenAI-API-compatible'),
                        ('模型名称', _entry_name),
                        ('模型类型', '文本生成 / LLM'),
                        ('API Base URL（Dify容器内）', 'http://host.docker.internal:8765/v1'),
                        ('API Base URL（宿主机客户端）', 'http://localhost:8765/v1'),
                        ('API Key', settings.GATEWAY_BEARER_TOKEN),
                    ]
                    ui.label(f'模型名称填「{_entry_name}」= 网关智能路由，自动选择最合适的真实模型（可修改：系统配置 → 对外模型名）').classes(
                        'text-xs text-blue-700 font-medium'
                    )
                    for label, value in config_items:
                        with ui.row().classes('items-center gap-2'):
                            ui.label(f'{label}:').classes('text-sm font-bold text-gray-600 w-32')
                            ui.label(value).classes('font-mono text-sm text-blue-700 flex-1')
                            ui.button(icon='content_copy', on_click=lambda v=value: [
                                ui.run_javascript(f'navigator.clipboard.writeText("{v}")'),
                                ui.notify(f'已复制 {label}', type='positive')
                            ]).props('flat dense size=sm color=primary').tooltip('复制')
            
            # 快速操作
            ui.label('快速操作').classes('text-2xl font-bold text-gray-800 mt-4')
            with ui.row().classes('gap-3'):
                ui.button('🆓 免费向导', on_click=lambda: ui.navigate.to('/wizard')).props('color=green size=lg')
                ui.button('新增账号', on_click=lambda: ui.navigate.to('/accounts')).props('color=primary size=lg')
                ui.button('系统配置', on_click=lambda: ui.navigate.to('/config')).props('color=secondary size=lg outline')
                ui.button('查看日志', on_click=lambda: ui.navigate.to('/logs')).props('color=accent size=lg outline')
                ui.button('▶ 路由省钱演示', on_click=lambda: ui.run_javascript("window.open('/admin/static/wg_routing_demo.html', '_blank')")).props('color=orange size=lg')
    
    
    @ui.page('/wizard')
    async def wizard_page():
        """免费向导（SPA）"""
        await build_spa('wizard')

    async def wizard_view():
        """免费向导视图（SPA tab 面板内容）"""
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
        from app.services.model_catalog_service import ModelCatalogService
        from app.utils.encryption import encryption_service

        extra_inputs = {}            # extra 字段输入框引用（detail 重建后重填）

        # 合并目录（内置 + DB 用户覆盖）+ 已接入厂商标记（按别名匹配，避免同名不同写法漏判）
        async with AsyncSessionLocal() as _s:
            vendors = await list_vendors_merged(_s)
            # 主从架构：模型挂在 ModelCatalog 下，从 catalog 统计已接入模型
            from app.models.database import ModelCatalog
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
                    from app.models.database import ModelCatalog
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
                    from app.models.database import ModelCatalog
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

    @ui.page('/accounts')
    async def accounts_page():
        """账号管理（SPA）"""
        await build_spa('accounts')

    async def accounts_view():
        """账号管理视图（SPA）——主从结构：厂商 → 账号（主）→ 模型清单（从）"""

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
                    async with AsyncSessionLocal() as session:
                        from app.services.model_catalog_service import ModelCatalogService
                        from app.services.embedding import EmbeddingService
                        from app.pipeline.config import PipelineConfig
                        cfg = await PipelineConfig.load(session)
                        embed_svc = EmbeddingService(cfg.router_config, db=session)
                        svc = ModelCatalogService(session)
                        count = await svc.recompute_all_embeddings(embed_svc)
                    ui.notify(f'已重算 {count} 个模型能力向量', type='positive')
                    ui.navigate.to('/accounts')
                except Exception as e:
                    ui.notify(f'重算失败: {e}', type='negative')

            with ui.row().classes('items-center justify-between w-full'):
                ui.label('账号模型管理').classes('text-3xl font-bold text-gray-800')
                with ui.row().classes('gap-2'):
                    ui.button('新增账号', on_click=lambda: show_account_dialog()).props('color=primary size=lg')

            accounts = await get_accounts()

            # 每账号的模型清单（catalog 按 account_id 聚合——主从语义，不再按模型名单映射）
            account_models = {}
            async with AsyncSessionLocal() as session:
                cat_result = await session.execute(select(ModelCatalog))
                for cat in cat_result.scalars().all():
                    account_models.setdefault(cat.account_id, []).append(cat)

            def mask_key(acc):
                """密钥脱敏：已配置显示首尾，未配置显示占位"""
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

    @ui.page('/config')
    async def config_page():
        """系统配置（SPA）"""
        await build_spa('config')

    async def config_view():
        """系统配置视图（SPA tab 面板内容）"""
        
        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            ui.label('全局系统配置').classes('text-3xl font-bold text-gray-800')
            ui.label('所有配置保存后立即生效，无需重启服务').classes('text-sm text-gray-500 -mt-2')

            # 获取当前配置
            config = await get_system_config()

            # 对外模型名（网关统一入口，单一数据源）
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('对外模型名（网关统一入口）').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('客户端（Dify/OpenClaw 等）配置模型时统一填这个名字，网关内部智能路由自动映射真实模型').classes('text-xs text-gray-500 mb-3')
                entry_name = ui.input(
                    '对外模型名',
                    value=getattr(config, 'virtual_entry_name', 'woolgate') or 'woolgate',
                ).classes('w-full max-w-md').props('placeholder=woolgate')
                ui.label('修改后，首页 Dify 配置示例、/v1/models 模型列表、路由判断将同步生效').classes('text-xs text-amber-600')
                with ui.expansion('为什么有这个字段？入口名 vs 真实模型名', icon='help').classes('w-full mt-1'):
                    ui.label('· 入口名（如 woolgate）：客户端只需填一个名字，网关智能路由自动选最合适/最省钱的模型，客户端无需了解后端模型结构').classes('text-xs text-gray-600 mb-1')
                    ui.label('· 真实模型名（如 deepseek-chat）：点名直走该模型，仍享受多账号比价、故障切换、统一账单').classes('text-xs text-gray-600 mb-1')
                    ui.label('· 两者都不是：返回明确报错，避免配置错误被静默掩盖').classes('text-xs text-gray-600')

            # 额度耗尽策略（卡片样式与管线策略页统一）
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
                    value=config.quota_exhaust_strategy,
                ).classes('w-full max-w-md')

            # 重试与日志（卡片样式与管线策略页统一）
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('重试与日志').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('请求失败重试、故障冷却与日志保留参数').classes('text-xs text-gray-500 mb-3')
                with ui.grid(columns=3).classes('w-full gap-x-8 gap-y-4'):
                    with ui.column().classes('gap-1'):
                        max_retry = ui.number('最大重试次数', value=config.max_retry_count, min=0, max=10).classes('w-full')
                        ui.label('请求失败后最多重试几次').classes('text-xs text-gray-400')
                    with ui.column().classes('gap-1'):
                        cool_down = ui.number('故障冷却（秒）', value=config.cool_down_seconds, min=0).classes('w-full')
                        ui.label('失败后暂停使用该账号的时长').classes('text-xs text-gray-400')
                    with ui.column().classes('gap-1'):
                        log_retention = ui.number('日志保留（天）', value=config.log_retention_days, min=1).classes('w-full')
                        ui.label('请求日志自动清理周期').classes('text-xs text-gray-400')

            # 保存按钮
            async def save():
                config_data = {
                    'quota_exhaust_strategy': quota_strategy.value,
                    'max_retry_count': int(max_retry.value),
                    'cool_down_seconds': int(cool_down.value),
                    'log_retention_days': int(log_retention.value),
                    'virtual_entry_name': (entry_name.value or 'woolgate').strip(),
                }
                success = await save_system_config(config_data)
                if success:
                    ui.notify('配置已保存', type='positive')
                else:
                    ui.notify('保存失败', type='negative')

            with ui.row().classes('w-full justify-end'):
                ui.button('保存配置', on_click=save).props('color=primary size=lg')

            # 企业版入口（开源版钩子：需要企业级能力时由此进入）
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

    @ui.page('/pipeline')
    async def pipeline_page():
        """管线策略（SPA）"""
        await build_spa('pipeline')

    async def pipeline_view():
        """管线策略视图（SPA tab 面板内容）"""

        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            ui.label('管线策略配置').classes('text-3xl font-bold text-gray-800')
            ui.label('三层策略串行：模型路由 → 账号调度 → 上下文管理，保存后立即生效').classes('text-sm text-gray-500 -mt-2')

            # 获取当前配置
            config = await get_system_config()

            # ── ① 模型路由 ──
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('① 模型路由策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('根据用户请求语义，智能选择最适合的模型').classes('text-xs text-gray-500 mb-3')

                router_strategy = ui.select(
                    {
                        'off': '关闭（不路由，直接用默认模型）',
                        'vector': '向量相似度匹配',
                        'llm': '大模型分类判断',
                        'hybrid': '混合（向量高置信直接用，低置信升级大模型）',
                    },
                    label='路由策略',
                    value=getattr(config, 'router_strategy', 'hybrid'),
                ).classes('w-full max-w-md mb-3')
                ui.label('默认开启智能路由：免费额度优先，自动选择性价比最高的模型').classes('text-xs text-blue-600 -mt-2 mb-2')

                # 加载当前 router_config
                from app.pipeline.config import PipelineConfig
                _pipeline_cfg = await PipelineConfig.load(AsyncSessionLocal())
                _router_cfg = _pipeline_cfg.router_config

                ui.label('Embedding 配置（向量 / 混合策略使用）').classes('text-sm font-bold text-gray-600 mt-2 mb-1')

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

                _embed_options = {0: '自动（选用第一个 Embedding 模型）'}
                for _m in _embed_models:
                    _acc = _accounts.get(_m.account_id)
                    _acc_name = _acc.vendor if _acc else '未知'
                    _embed_options[_m.id] = f"{_m.display_name or _m.model_name}（{_acc_name}）"

                embedding_model_id = ui.select(
                    options=_embed_options,
                    label='Embedding 模型',
                    value=getattr(_router_cfg, 'embedding_model_id', 0) or 0,
                ).classes('w-full max-w-md')
                if not _embed_models:
                    ui.label('暂无 Embedding 模型，请先在账号管理中启用').classes('text-xs text-red-500 -mt-1 mb-3')
                else:
                    ui.label('选择后自动使用该模型所属账号的 API Key，无需单独配置').classes('text-xs text-gray-400 -mt-1 mb-3')

                # edition 分组：opensource 折叠高级参数，enterprise 展开
                _is_enterprise = getattr(config, 'edition', 'opensource') == 'enterprise'

                with ui.expansion('高级参数（阈值微调 · 上下文细节 · 本地运行时）', icon='tune',
                                  value=_is_enterprise).classes('w-full'):
                    ui.label('开源版默认使用智能推荐参数，以下为极客微调项').classes('text-xs text-gray-400 -mt-1 mb-2')

                    ui.label('滞回阈值（防止频繁切换模型）').classes('text-sm font-bold text-gray-600 mt-1 mb-1')
                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            threshold_high = ui.number(
                                '切入阈值', value=_router_cfg.threshold_high,
                                min=0.0, max=1.0, step=0.05,
                            ).classes('w-full')
                            ui.label('匹配度高于此值才切换模型').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            threshold_low = ui.number(
                                '保持阈值', value=_router_cfg.threshold_low,
                                min=0.0, max=1.0, step=0.05,
                            ).classes('w-full')
                            ui.label('匹配度低于此值才允许切走，中间区间保持当前模型').classes('text-xs text-gray-400')

            # ── ② 账号调度 ──
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('② 账号调度策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('从可用账号池中选择具体账号，管理免费额度消耗顺序').classes('text-xs text-gray-500 mb-3')

                selector_strategy = ui.select(
                    {
                        'pin': '指定模型（默认）',
                        'free-first': '免费额度优先',
                        'round-robin': '轮询',
                        'sticky': '会话粘性',
                        'failover': '主备切换',
                        'cost-first': '成本最低',
                    },
                    label='调度策略',
                    value=getattr(config, 'selector_strategy', 'pin'),
                ).classes('w-full max-w-md')
                ui.label('同一模型存在多个账号时，按此策略决定使用顺序').classes('text-xs text-gray-400 -mt-1')

            # ── ③ 上下文管理 ──
            with ui.card().classes('w-full shadow-lg p-4'):
                ui.label('③ 上下文管理策略').classes('text-base font-bold text-gray-700 mb-1')
                ui.label('控制发送给上游的消息组装方式，平衡上下文完整性与 token 消耗').classes('text-xs text-gray-500 mb-3')

                context_strategy = ui.select(
                    {
                        'passthrough': '直传（默认，完整上下文）',
                        'window': '滑动窗口（只保留最近 N 轮）',
                        'summary': '摘要压缩（长对话自动摘要）',
                    },
                    label='上下文策略',
                    value=getattr(config, 'context_strategy', 'passthrough'),
                ).classes('w-full max-w-md mb-3')

                _context_cfg = _pipeline_cfg.context_config

                with ui.expansion('上下文细节（窗口轮数 · 摘要参数）', icon='tune',
                                  value=_is_enterprise).classes('w-full'):
                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            window_turns = ui.number(
                                '保留最近 N 轮对话', value=_context_cfg.window_turns, min=1, max=100
                            ).classes('w-full')
                            ui.label('滑动窗口策略下保留的对话轮数').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            summary_provider = ui.select(
                                {'cloud': '云端模型', 'local': '本地模型（Ollama）'},
                                label='摘要模型来源',
                                value=_context_cfg.summary_provider,
                            ).classes('w-full')
                            ui.label('摘要压缩策略使用哪种模型生成摘要').classes('text-xs text-gray-400')

                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            summary_model = ui.input(
                                '摘要模型名', value=_context_cfg.summary_model
                            ).classes('w-full')
                            ui.label('云端：从账号池选该模型的启用账号；本地：直接调用').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            summary_window_turns = ui.number(
                                '摘要后保留原文轮数', value=_context_cfg.summary_window_turns, min=0, max=20
                            ).classes('w-full')
                            ui.label('触发摘要后，最近 N 轮原文仍完整保留').classes('text-xs text-gray-400')

                    with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                        with ui.column().classes('gap-1'):
                            summary_trigger_turns = ui.number(
                                '触发阈值（对话轮数）', value=_context_cfg.summary_trigger_turns, min=1
                            ).classes('w-full')
                            ui.label('对话轮数超过该值且满足 token 阈值时触发').classes('text-xs text-gray-400')
                        with ui.column().classes('gap-1'):
                            summary_trigger_tokens = ui.number(
                                '触发阈值（token 数）', value=_context_cfg.summary_trigger_tokens, min=100
                            ).classes('w-full')
                            ui.label('累计 token 超过该值且满足轮数阈值时触发').classes('text-xs text-gray-400')

                    ui.label('跨模型切换时强制触发摘要，保证上下文不丢失').classes('text-xs text-blue-600 mt-1')

            # ── ④ 本地模型运行时 ──
            with ui.expansion('本地模型运行时（Ollama，高级）', icon='computer', value=_is_enterprise).classes('w-full'):
                ui.label('用于本地 Embedding、摘要等轻量任务，不参与主模型调度').classes('text-xs text-gray-500 mb-2')
                with ui.grid(columns=2).classes('w-full gap-x-8 gap-y-4 max-w-2xl'):
                    with ui.column().classes('gap-1'):
                        ollama_enabled = ui.checkbox('启用 Ollama', value=config.ollama_enabled)
                        ui.label('关闭后所有本地模型账号跳过调度').classes('text-xs text-gray-400')
                    with ui.column().classes('gap-1'):
                        ollama_url = ui.input('Ollama 地址', value=config.ollama_base_url).classes('w-full')
                        ui.label('默认 http://localhost:11434').classes('text-xs text-gray-400')

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

            with ui.row().classes('w-full justify-end'):
                ui.button('保存策略', on_click=save_pipeline).props('color=primary size=lg')



    @ui.page('/logs')
    async def logs_page():
        """请求日志（SPA）"""
        await build_spa('logs')

    @ui.page('/plugins')
    async def plugins_page():
        """插件管理（SPA）"""
        await build_spa('plugins')

    async def logs_view():
        """请求日志视图（SPA tab 面板内容）"""

        @ui.refreshable
        async def logs_content():
            """请求日志视图（SPA tab 面板内容）"""
        
            with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
                with ui.row().classes('items-center justify-between w-full'):
                    ui.label('请求日志').classes('text-3xl font-bold text-gray-800')
                    ui.button('刷新', on_click=logs_content.refresh).props('outline color=primary')
            
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
                            ui.label((icon + ' ') if icon else title).classes('text-sm text-gray-600')
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
                        log_created = local_fmt(log.created_at)
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

    async def plugins_view():
        """插件管理视图（SPA tab 面板内容）——重新设计版"""

        @ui.refreshable
        async def plugins_content():
            from app.extensions.loader import get_plugin_registry, get_plugin_stats
            from app.extensions.sdk import config_registry as _cfg_reg, get_plugin_config, set_plugin_config

            stats = get_plugin_stats()
            registry = get_plugin_registry()
            all_configs = _cfg_reg.list()

            with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
                # ═══ 标题 ═══
                with ui.row().classes('items-center justify-between w-full'):
                    ui.label('🔌 插件管理').classes('text-3xl font-bold text-gray-800')
                    ui.button('🔄 刷新', on_click=plugins_content.refresh).props('outline color=primary')

                # ═══ 一、概览统计 ═══
                def stat_card(icon, title, value, sub=None, color='blue'):
                    with ui.card().classes(f'flex-1 border-l-4 border-{color}-500').style('height:100px'):
                        with ui.column().classes('w-full items-center gap-1 justify-center').style('height:100%'):
                            ui.label(icon).classes('text-xl')
                            ui.label(str(value)).classes('text-2xl font-bold')
                            ui.label(title).classes('text-xs text-gray-500')
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
                                                                    on_click=lambda p=target_name: ui.run_javascript(
                                                                        f'var el=document.querySelector("[data-plugin=\\\"{p}\\\"]");'
                                                                        f'if(el){{el.scrollIntoView({{behavior:"smooth",block:"center"}});'
                                                                        f'var blinkCount=0;var blinkInterval=setInterval(function(){{'
                                                                        f'if(blinkCount%2===0){{el.classList.add("ring-2","ring-blue-400")}}else{{el.classList.remove("ring-2","ring-blue-400")}};'
                                                                        f'blinkCount++;if(blinkCount>=6){{clearInterval(blinkInterval);el.classList.remove("ring-2","ring-blue-400")}}}},500);}}'
                                                                    )
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

        await plugins_content()

def _type_label(t):
    """模型类型显示汉化"""
    return {'chat': '对话', 'embedding': '向量', 'image': '图像', 'video': '视频', 'audio': '音频'}.get(t or 'chat', t or 'chat')


_plugin_page_refs = []

def _register_plugin_pages():
    from app.extensions.sdk import page_registry
    print(f"[插件系统] 模块级别注册插件页面，page_registry 内容: {page_registry.list()}")
    for route, page_info in page_registry.list().items():
        full_route = route if route.startswith('/') else '/' + route
        render_func = page_info['render']
        page_title = page_info.get('title', '插件页面')
        print(f"[插件系统] 注册插件页面: {full_route} ({page_title})")

        def _make_plugin_page(rf, pt, fr):
            @ui.page(fr)
            async def plugin_page(request: Request):
                ui.colors(primary='#667eea', secondary='#764ba2')
                with ui.header().classes('items-center justify-between px-6 shadow-lg').style('background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);'):
                    with ui.row().classes('items-center gap-4'):
                        ui.label('🐑').classes('text-4xl')
                        ui.label('WoolGate').classes('text-2xl font-bold text-white')
                    ui.button('← 返回首页', on_click=lambda: ui.navigate.to('/admin/')).props('flat no-caps text-color=white')
                with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
                    try:
                        if callable(rf):
                            result = rf(request) if 'request' in rf.__code__.co_varnames else rf()
                            if hasattr(result, '__await__'):
                                await result
                    except Exception as e:
                        ui.card().classes('w-full bg-red-50 border-l-4 border-red-500 p-4')
                        ui.label(f'插件页面渲染异常: {e}').classes('text-red-700')
            return plugin_page

        _plugin_page_refs.append(_make_plugin_page(render_func, page_title, full_route))


def init_ui(fastapi_app):
    """初始化NiceGUI并挂载到FastAPI"""
    create_ui()
    _register_plugin_pages()
    # 显式挂载静态目录（含路由省钱演示页等），容器内项目根 /app/static
    _static_dir = Path(__file__).resolve().parent.parent.parent / 'static'
    if _static_dir.exists():
        app.add_static_files('/static', str(_static_dir))
    ui.run_with(
        fastapi_app,
        mount_path='/admin',
        storage_secret='woolgate-ui-secret-key-2026'
    )