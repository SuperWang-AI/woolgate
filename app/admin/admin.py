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

# 从 services.py 导入数据层函数
from app.admin.services import get_stats, get_trend_data

# 从 services.py 导入数据层函数
from app.admin.services import get_stats, get_trend_data, get_accounts, get_system_config

# 从 services.py 导入更多函数
from app.admin.services import (
    get_stats, get_trend_data, get_accounts, get_system_config,
    save_system_config, build_onboarding_data, ONBOARD_ANSWERS_CN
)

# 从 services.py 导入启动引导函数
from app.admin.services import apply_onboard_profile

def create_ui():
    """创建UI"""

    # ═══ SPA 全局状态 ═══
    _tabs_ref = None          # 当前tabs对象引用，用于SPA内导航
    _plugin_active = None     # 当前激活的插件key（用于插件页面动态渲染）
    _plugin_refresh = None    # 插件页面刷新回调（SPA内切换插件时调用）

    # SPA 路由映射：路由路径 ↔ tab key（插件统一使用 /plugins?active=xxx）
    PATH_TO_KEY = {'/': 'home', '/wizard': 'wizard', '/accounts': 'accounts', '/config': 'config', '/pipeline': 'pipeline', '/logs': 'logs', '/plugins': 'plugins'}
    KEY_TO_PATH = {v: k for k, v in PATH_TO_KEY.items()}

    from app.admin.utils import spa_navigate, init_spa_state, set_plugin_active, set_plugin_refresh

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



    async def build_spa(active_key: str, request: Optional[Request] = None):
        """SPA 根：导航 tabs + 内容面板，导航切换零刷新（URL 用 history.replaceState 同步，刷新后仍停留当前页）"""
        nonlocal _plugin_active
        ui.page_title('WoolGate AI 聚合网关')
        

        # 从URL解析初始插件active状态
        if request is not None and active_key == 'plugins':
            _plugin_active = request.query_params.get('active', None)
            # 同步到 utils.py 中的全局变量
            from app.admin.utils import set_plugin_active
            set_plugin_active(_plugin_active)
        
        # 从 components 导入导航栏
        from app.admin.components.navigation import render_navigation
        tabs = render_navigation(active_key)

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

        # 从 pages 导入页面类
        from app.admin.pages.dashboard import DashboardPage
        from app.admin.pages.wizard import WizardPage
        from app.admin.pages.accounts import AccountsPage
        from app.admin.pages.config import ConfigPage
        from app.admin.pages.pipeline import PipelinePage
        from app.admin.pages.logs import LogsPage
        from app.admin.pages.plugins import PluginsPage

        with ui.tab_panels(tabs, value=active_key).classes('w-full'):
            with ui.tab_panel('home'):
                page = DashboardPage(None, {}, request=request)
                await page.load()
                await page.render()
            with ui.tab_panel('wizard'):
                page = WizardPage(None, {})
                await page.load()
                await page.render()
            with ui.tab_panel('accounts'):
                page = AccountsPage(None, {})
                await page.load()
                await page.render()
            with ui.tab_panel('config'):
                page = ConfigPage(None, {})
                await page.load()
                await page.render()
            with ui.tab_panel('pipeline'):
                page = PipelinePage(None, {})
                await page.load()
                await page.render()
            with ui.tab_panel('logs'):
                page = LogsPage(None, {})
                await page.load()
                await page.render()
            with ui.tab_panel('plugins'):
                page = PluginsPage(None, {}, request=request)
                await page.load()
                await page.render()
                # 设置插件页面刷新回调（SPA内切换插件时调用）
                set_plugin_refresh(page.refresh)

    @ui.page('/')
    async def index(request: Request):
        """首页（SPA）"""
        await build_spa('home', request)
    
    @ui.page('/wizard')
    async def wizard_page(request: Request):
        """免费向导（SPA）"""
        await build_spa('wizard', request)
    
    @ui.page('/accounts')
    async def accounts_page(request: Request):
        """账号管理（SPA）"""
        await build_spa('accounts', request)
    
    @ui.page('/config')
    async def config_page(request: Request):
        """系统配置（SPA）"""
        await build_spa('config', request)
    
    @ui.page('/pipeline')
    async def pipeline_page(request: Request):
        """管线策略（SPA）"""
        await build_spa('pipeline', request)
    
    @ui.page('/logs')
    async def logs_page(request: Request):
        """请求日志（SPA）"""
        await build_spa('logs', request)
    
    @ui.page('/plugins')
    async def plugins_page(request: Request):
        """插件管理（SPA）"""
        await build_spa('plugins', request)

def init_ui(fastapi_app):
    """初始化NiceGUI并挂载到FastAPI"""
    create_ui()
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