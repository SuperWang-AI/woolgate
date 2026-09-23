"""
导航栏组件
包含顶部导航、插件下拉菜单、全局样式
"""
from __future__ import annotations
from typing import Optional
from nicegui import ui


def render_page_head():
    """全局 head：品牌图标 + 全局样式 + 插件下拉菜单 JS"""
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


def render_navigation(active_key: str = "home"):
    """
    渲染顶部导航栏
    
    Args:
        active_key: 当前激活的导航项
    """
    from app.extensions.sdk import nav_registry
    from app.admin.utils import spa_navigate, init_spa_state
    
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
    
    render_page_head()
    
    with ui.header().classes('header-gradient items-center justify-between px-6 shadow-lg').style('overflow: visible'):
        with ui.row().classes('items-center gap-4'):
            ui.label('🐑').classes('text-4xl')
            ui.label('WoolGate').classes('text-2xl font-bold text-white')
        with ui.row().classes('items-center gap-1'):
            with ui.tabs().props('dense active-color=white indicator-color=white text-color=white').classes('gap-1') as tabs:
                # 初始化 utils.py 中的 SPA 全局状态
                init_spa_state(tabs)
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
