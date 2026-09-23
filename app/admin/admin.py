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

def format_local_time(dt):
    """UTC naive datetime → 本地时区展示字符串"""
    if not dt:
        return '未知'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')

def get_today_start_utc():
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
        today_start = get_today_start_utc()
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


async def get_trend_data(days: int = 7):
    """获取最近N天的趋势数据（请求量、成本、Token、模型分布）"""
    async with AsyncSessionLocal() as session:
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=days - 1)
        
        # 按天统计请求量、成功量、成本、Token
        result = await session.execute(
            select(
                func.date(RequestLog.created_at).label('date'),
                func.count(RequestLog.id).label('total'),
                func.sum(case((RequestLog.status == "success", 1), else_=0)).label('success'),
                func.sum(RequestLog.actual_cost).label('cost'),
                func.sum(RequestLog.prompt_tokens).label('prompt_tokens'),
                func.sum(RequestLog.completion_tokens).label('completion_tokens'),
            )
            .where(RequestLog.created_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc))
            .group_by(func.date(RequestLog.created_at))
            .order_by(func.date(RequestLog.created_at))
        )
        daily_stats = {}
        for row in result.all():
            daily_stats[str(row.date)] = {
                'total': row.total or 0,
                'success': row.success or 0,
                'cost': float(row.cost or 0),
                'prompt_tokens': row.prompt_tokens or 0,
                'completion_tokens': row.completion_tokens or 0,
            }
        
        # 补齐缺失的日期
        dates = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            dates.append(str(d))
            if str(d) not in daily_stats:
                daily_stats[str(d)] = {'total': 0, 'success': 0, 'cost': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
        
        # 模型使用分布（累计）
        result = await session.execute(
            select(
                RequestLog.routed_model,
                func.count(RequestLog.id).label('count'),
            )
            .where(RequestLog.routed_model.isnot(None))
            .group_by(RequestLog.routed_model)
            .order_by(desc(func.count(RequestLog.id)))
            .limit(10)
        )
        model_distribution = []
        for row in result.all():
            model_distribution.append({'name': row.routed_model or 'unknown', 'value': row.count or 0})
        
        return {
            'dates': dates,
            'daily': daily_stats,
            'model_distribution': model_distribution,
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

def build_onboarding_data(answers: dict):
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
    data, profile_name = build_onboarding_data(answers)
    ok = await save_system_config(data)
    if ok:
        # 使管线配置缓存失效，新策略立即生效
        from app.pipeline.config import PipelineConfig
        PipelineConfig.invalidate_cache()
    return ok, profile_name


def create_ui():
    """创建UI"""

    # ═══ SPA 全局状态 ═══
    _tabs_ref = None          # 当前tabs对象引用，用于SPA内导航
    _plugin_active = None     # 当前激活的插件key（用于插件页面动态渲染）
    _plugin_refresh = None    # 插件页面刷新回调（SPA内切换插件时调用）

    # SPA 路由映射：路由路径 ↔ tab key（插件统一使用 /plugins?active=xxx）
    PATH_TO_KEY = {'/': 'home', '/wizard': 'wizard', '/accounts': 'accounts', '/config': 'config', '/pipeline': 'pipeline', '/logs': 'logs', '/plugins': 'plugins'}
    KEY_TO_PATH = {v: k for k, v in PATH_TO_KEY.items()}

    def spa_navigate(key: str, active: str = None):
        """SPA内导航：切换tab value + 同步URL，不触发整页刷新"""
        nonlocal _plugin_active
        if _tabs_ref is not None:
            _tabs_ref.value = key
        # 同步URL（不刷新页面）
        if key == 'plugins' and active:
            ui.run_javascript(f"history.replaceState(null, '', '/admin/plugins?active={active}')")
            _plugin_active = active
            # 触发插件页面刷新（SPA内切换插件）
            if _plugin_refresh is not None:
                _plugin_refresh()
        else:
            path = KEY_TO_PATH.get(key, '/')
            ui.run_javascript(f"history.replaceState(null, '', '/admin{path}')")
            if key == 'plugins':
                # 切回插件管理页面：重置active并刷新
                _plugin_active = None
                if _plugin_refresh is not None:
                    _plugin_refresh()
            else:
                _plugin_active = None
        # 关闭插件下拉菜单
        ui.run_javascript("var dd = document.getElementById('plugin-dropdown-menu'); if(dd) dd.classList.add('hidden');")

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
<script>
function toggleDropdown(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.toggle('hidden');
    }
}
function showDropdown(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
}
function hideDropdown(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
}
// 插件按钮hover显示下拉菜单（MutationObserver等待NiceGUI渲染完成，替代轮询）
function initPluginDropdownHover() {
    const pluginBtn = document.getElementById('plugin-nav-btn');
    const dropdown = document.getElementById('plugin-dropdown-menu');
    if (!pluginBtn || !dropdown) {
        // 元素尚未渲染，用 MutationObserver 等待 DOM 变化
        const observer = new MutationObserver(function(mutations, obs) {
            const btn = document.getElementById('plugin-nav-btn');
            const dd = document.getElementById('plugin-dropdown-menu');
            if (btn && dd) {
                obs.disconnect();
                bindHoverEvents(btn, dd);
            }
        });
        // 兼容 document.body 尚未创建的情况（NiceGUI 早期执行 JS 时 body 可能为 null）
        const observeTarget = document.body || document.documentElement;
        if (observeTarget) {
            observer.observe(observeTarget, { childList: true, subtree: true });
        } else {
            // 极端情况：连 documentElement 都没有，等待 DOMContentLoaded
            document.addEventListener('DOMContentLoaded', function() {
                initPluginDropdownHover();
            });
        }
        return;
    }
    bindHoverEvents(pluginBtn, dropdown);
}
function bindHoverEvents(pluginBtn, dropdown) {
    let hideTimer = null;
    pluginBtn.addEventListener('mouseenter', function() {
        if (hideTimer) clearTimeout(hideTimer);
        showDropdown('plugin-dropdown-menu');
    });
    pluginBtn.addEventListener('mouseleave', function() {
        hideTimer = setTimeout(function() {
            hideDropdown('plugin-dropdown-menu');
        }, 200);
    });
    dropdown.addEventListener('mouseenter', function() {
        if (hideTimer) clearTimeout(hideTimer);
    });
    dropdown.addEventListener('mouseleave', function() {
        hideDropdown('plugin-dropdown-menu');
    });
}
initPluginDropdownHover();
document.addEventListener('click', function(e) {
    const dropdowns = document.querySelectorAll('[id$="-dropdown-menu"]');
    dropdowns.forEach(function(d) {
        if (!d.contains(e.target) && !e.target.closest('button')) {
            d.classList.add('hidden');
        }
    });
});
</script>
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

    def nav_tabs(active_key: str):
        """SPA 顶部导航 tabs：点击仅前端切换面板，无整页刷新（插件统一聚合入口，带下拉列表）"""
        nonlocal _tabs_ref
        page_head()
        with ui.header().classes('header-gradient items-center justify-between px-6 shadow-lg').style('overflow: visible'):
            with ui.row().classes('items-center gap-4'):
                ui.label('🐑').classes('text-4xl')
                ui.label('WoolGate').classes('text-2xl font-bold text-white')
            with ui.row().classes('items-center gap-1'):
                with ui.tabs().props('dense active-color=white indicator-color=white text-color=white').classes('gap-1') as tabs:
                    _tabs_ref = tabs  # 保存tabs引用供SPA导航使用
                    # 内置页面tab（除了插件管理）
                    for label, path, key in NAV_PAGES:
                        if key != 'plugins':
                            ui.tab(name=key, label=label)
                # 插件聚合入口：按钮+自定义下拉面板（JavaScript控制显示）
                plugin_dropdown_id = 'plugin-dropdown-menu'
                ui.button('🔌 插件 ▼').props('flat color=white dense id=plugin-nav-btn').classes('text-white')
                # 下拉面板（默认隐藏）
                with ui.card().classes('absolute top-full right-0 mt-1 shadow-xl z-50 hidden').style('min-width: 240px;') as dropdown_card:
                    dropdown_card.props(f'id={plugin_dropdown_id}')
                    with ui.column().classes('gap-0 p-0'):
                        # 插件管理入口
                        ui.button('📋 插件管理', on_click=lambda: spa_navigate('plugins')).props('flat align=left').classes('w-full text-left text-gray-700 hover:bg-gray-100')
                        ui.separator()
                        # 已启用插件列表（只有注入前端页面的插件才会注册到nav_registry）
                        for nav_item in nav_registry.list():
                            plugin_key = nav_item['route'].strip('/')
                            desc = nav_item.get('description', '')
                            label_text = nav_item['label']
                            if desc:
                                label_text = f"{label_text}  —  {desc}"
                            ui.button(label_text, on_click=lambda k=plugin_key: spa_navigate('plugins', active=k)).props('flat align=left').classes('w-full text-left text-gray-700 hover:bg-gray-100')
        return tabs

    async def build_spa(active_key: str, request: Optional[Request] = None):
        """SPA 根：导航 tabs + 内容面板，导航切换零刷新（URL 用 history.replaceState 同步，刷新后仍停留当前页）"""
        nonlocal _plugin_active
        ui.page_title('WoolGate AI 聚合网关')
        # 从URL解析初始插件active状态
        if request is not None and active_key == 'plugins':
            _plugin_active = request.query_params.get('active', None)
        tabs = nav_tabs(active_key)

        def sync_url(e):
            nonlocal _plugin_active
            path = KEY_TO_PATH.get(e.value, '/')
            if e.value == 'plugins' and _plugin_active:
                ui.run_javascript(f"history.replaceState(null, '', '/admin/plugins?active={_plugin_active}')")
            else:
                ui.run_javascript(f"history.replaceState(null, '', '/admin{path}')")
            if e.value != 'plugins':
                _plugin_active = None

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
                await plugins_view(request)

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
                        spa_navigate('wizard')
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
            
            # ── 数据趋势可视化 ──
            trend_data = await get_trend_data(days=7)
            ui.label('数据趋势').classes('text-2xl font-bold text-gray-800 mt-4')
            ui.add_head_html('<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>')

            chart_dates = trend_data['dates']
            chart_requests = [trend_data['daily'][d]['total'] for d in chart_dates]
            chart_success = [trend_data['daily'][d]['success'] for d in chart_dates]
            chart_costs = [round(trend_data['daily'][d]['cost'], 4) for d in chart_dates]
            chart_prompt = [round(trend_data['daily'][d]['prompt_tokens'] / 1000, 1) for d in chart_dates]
            chart_completion = [round(trend_data['daily'][d]['completion_tokens'] / 1000, 1) for d in chart_dates]
            chart_model_dist = json.dumps(trend_data['model_distribution'], ensure_ascii=False)
            chart_dates_json = json.dumps(chart_dates)
            chart_requests_json = json.dumps(chart_requests)
            chart_success_json = json.dumps(chart_success)
            chart_costs_json = json.dumps(chart_costs)
            chart_prompt_json = json.dumps(chart_prompt)
            chart_completion_json = json.dumps(chart_completion)

            # 用纯HTML渲染图表区域，完全控制布局
            charts_html = (
                '<div style="display:flex;flex-wrap:wrap;gap:16px;margin-top:16px;">'
                '<div style="flex:1;min-width:400px;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);padding:16px;">'
                '<div style="font-size:14px;font-weight:600;color:#4b5563;margin-bottom:8px;">最近7天请求趋势</div>'
                '<div id="chart-requests" style="width:100%;height:320px;"></div>'
                '</div>'
                '<div style="flex:1;min-width:400px;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);padding:16px;">'
                '<div style="font-size:14px;font-weight:600;color:#4b5563;margin-bottom:8px;">模型使用分布（累计TOP10）</div>'
                '<div id="chart-model-dist" style="width:100%;height:320px;"></div>'
                '</div>'
                '</div>'
                '<div style="display:flex;flex-wrap:wrap;gap:16px;margin-top:16px;">'
                '<div style="flex:1;min-width:400px;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);padding:16px;">'
                '<div style="font-size:14px;font-weight:600;color:#4b5563;margin-bottom:8px;">最近7天实际成本</div>'
                '<div id="chart-cost" style="width:100%;height:320px;"></div>'
                '</div>'
                '<div style="flex:1;min-width:400px;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);padding:16px;">'
                '<div style="font-size:14px;font-weight:600;color:#4b5563;margin-bottom:8px;">最近7天Token消耗（K）</div>'
                '<div id="chart-tokens" style="width:100%;height:320px;"></div>'
                '</div>'
                '</div>'
            )
            ui.html(charts_html)

                        # ECharts初始化脚本
            _script = (
                '<script>(function(){'
                'function initCharts(){'
                'if(typeof echarts==="undefined"){setTimeout(initCharts,200);return;}'
                'try{'
                'if(!document.getElementById("chart-requests"))return;'
                'var c1=echarts.init(document.getElementById("chart-requests"));'
                'c1.setOption({tooltip:{trigger:"axis"},legend:{data:["总请求","成功"],bottom:0},grid:{left:"3%",right:"4%",bottom:"15%",containLabel:true},xAxis:{type:"category",data:' + chart_dates_json + ',axisLabel:{fontSize:10}},yAxis:{type:"value"},series:[{name:"总请求",type:"line",data:' + chart_requests_json + ',smooth:true,itemStyle:{color:"#8b5cf6"},areaStyle:{opacity:0.1}},{name:"成功",type:"line",data:' + chart_success_json + ',smooth:true,itemStyle:{color:"#10b981"}}]});'
                'var c2=echarts.init(document.getElementById("chart-model-dist"));'
                'c2.setOption({tooltip:{trigger:"item"},legend:{orient:"horizontal",bottom:0,type:"scroll",textStyle:{fontSize:10}},series:[{type:"pie",radius:["35%","65%"],center:["50%","42%"],avoidLabelOverlap:true,itemStyle:{borderRadius:6,borderColor:"#fff",borderWidth:2},label:{show:false},emphasis:{label:{show:true,fontSize:14,fontWeight:"bold"}},data:' + chart_model_dist + '}]});'
                'var c3=echarts.init(document.getElementById("chart-cost"));'
                'c3.setOption({tooltip:{trigger:"axis"},grid:{left:"3%",right:"4%",bottom:"15%",containLabel:true},xAxis:{type:"category",data:' + chart_dates_json + ',axisLabel:{fontSize:10}},yAxis:{type:"value",name:"元"},series:[{name:"实际成本",type:"bar",data:' + chart_costs_json + ',itemStyle:{color:"#f59e0b",borderRadius:[4,4,0,0]},barWidth:"50%"}]});'
                'var c4=echarts.init(document.getElementById("chart-tokens"));'
                'c4.setOption({tooltip:{trigger:"axis"},legend:{data:["输入Token","输出Token"],bottom:0},grid:{left:"3%",right:"4%",bottom:"15%",containLabel:true},xAxis:{type:"category",boundaryGap:false,data:' + chart_dates_json + ',axisLabel:{fontSize:10}},yAxis:{type:"value",name:"K"},series:[{name:"输入Token",type:"line",data:' + chart_prompt_json + ',smooth:true,itemStyle:{color:"#3b82f6"},areaStyle:{opacity:0.2}},{name:"输出Token",type:"line",data:' + chart_completion_json + ',smooth:true,itemStyle:{color:"#ec4899"},areaStyle:{opacity:0.2}}]});'
                'window.addEventListener("resize",function(){c1.resize();c2.resize();c3.resize();c4.resize();});'
                '}catch(e){console.error("charts error:",e);}'
                '}'
                'if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",initCharts);}else{initCharts();}'
                '})();</script>'
            )
            ui.add_body_html(_script)

            # API 配置信息卡片            # API 配置信息卡片
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
                _entry_name = getattr(_dash_cfg, 'virtual_model_name', 'woolgate') or 'woolgate'
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
                ui.button('🆓 免费向导', on_click=lambda: spa_navigate('wizard')).props('color=green size=lg')
                ui.button('新增账号', on_click=lambda: spa_navigate('accounts')).props('color=primary size=lg')
                ui.button('系统配置', on_click=lambda: spa_navigate('config')).props('color=secondary size=lg outline')
                ui.button('查看日志', on_click=lambda: spa_navigate('logs')).props('color=accent size=lg outline')
                ui.button('▶ 路由省钱演示', on_click=lambda: ui.run_javascript("window.open('/admin/static/wg_routing_demo.html', '_blank')")).props('color=orange size=lg')
    
    
    @ui.page('/wizard')
    async def wizard_page():
        """免费向导（SPA）"""
        await build_spa('wizard')

    async def wizard_view():
        """免费向导视图（SPA tab 面板内容）"""
        from app.admin.pages.wizard import WizardPage
        page = WizardPage(db=None, config=None)
        await page.render()

    @ui.page('/accounts')
    async def accounts_page():
        """账号管理（SPA）"""
        await build_spa('accounts')

    async def accounts_view():
        """账号管理视图（SPA）——主从结构：厂商 → 账号（主）→ 模型清单（从）"""
        from app.admin.pages.accounts import AccountsPage
        page = AccountsPage(db=None, config=None)
        await page.load()
        await page.render()

    @ui.page('/config')
    async def config_page():
        """系统配置（SPA）"""
        await build_spa('config')

    async def config_view():
        """系统配置视图（SPA tab 面板内容）"""
        from app.admin.pages.config import ConfigPage
        page = ConfigPage(db=None, config=None)
        await page.load()
        await page.render()

    @ui.page('/pipeline')
    async def pipeline_page():
        """管线策略（SPA）"""
        await build_spa('pipeline')

    async def pipeline_view():
        """管线策略视图（SPA tab 面板内容）"""
        from app.admin.pages.pipeline import PipelinePage
        page = PipelinePage(db=None, config=None)
        await page.load()
        await page.render()

    @ui.page('/logs')
    async def logs_page():
        """请求日志（SPA）"""
        await build_spa('logs')

    @ui.page('/plugins')
    async def plugins_page(request: Request):
        """插件管理（SPA，支持?active=xxx显示指定插件内容）"""
        await build_spa('plugins', request)

    async def logs_view():
        """请求日志视图（SPA tab 面板内容）"""
        from app.admin.pages.logs import LogsPage
        page = LogsPage(db=None, config=None)
        await page.render()

    @ui.page('/plugins')
    async def plugins_page(request: Request):
        """插件管理（SPA，支持?active=xxx显示指定插件内容）"""
        await build_spa('plugins', request)

    async def plugins_view(request: Optional[Request] = None):
        """插件管理视图（SPA tab 面板内容）"""
        from app.admin.pages.plugins import PluginsPage
        page = PluginsPage(db=None, config=None, request=request, plugin_active=_plugin_active)
        await page.render()

def _type_label(t):
    """模型类型显示汉化"""
    return {'chat': '对话', 'embedding': '向量', 'image': '图像', 'video': '视频', 'audio': '音频'}.get(t or 'chat', t or 'chat')


def _log_plugin_pages():
    """插件页面已集成到SPA架构中，此处仅记录日志，不再注册独立页面路由"""
    from app.extensions.sdk import page_registry
    print(f"[插件系统] 插件页面已集成到SPA架构，page_registry 内容: {page_registry.list()}")
    for route, page_info in page_registry.list().items():
        full_route = route if route.startswith('/') else '/' + route
        page_title = page_info.get('title', '插件页面')
        print(f"[插件系统] SPA插件页面: {full_route} ({page_title})")


def init_ui(fastapi_app):
    """初始化NiceGUI并挂载到FastAPI"""
    create_ui()
    _log_plugin_pages()
    # 显式挂载静态目录（含路由省钱演示页等），容器内项目根 /app/static
    _static_dir = Path(__file__).resolve().parent.parent.parent / 'static'
    print(f'[UI] 静态文件目录: {_static_dir} (存在: {_static_dir.exists()})')
    if _static_dir.exists():
        app.add_static_files('/static', str(_static_dir))
    ui.run_with(
        fastapi_app,
        mount_path='/admin',
        storage_secret='woolgate-ui-secret-key-2026'
    )