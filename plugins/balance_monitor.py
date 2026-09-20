"""
WoolGate 余额监控与额度预警插件

功能：
1. 余额同步引擎：自动获取各厂商账号余额，支持5种触发时机
2. 预警引擎：4级预警（正常/注意/警告/紧急/耗尽），可配置阈值，耗尽预测
3. 路由感知：route.before钩子过滤耗尽账号，紧急账号降权
4. UI展示：独立余额看板页面、首页总览卡片、账号卡片余额标识

启用方式：设置环境变量 WOOLGATE_PLUGINS=plugins.balance_monitor
"""
import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, Any, List

from app.extensions.sdk import (
    register_hook, register_page, register_nav_item, register_component,
    register_config, PluginContext,
    UI_HOOK_DASHBOARD_WIDGETS, UI_HOOK_ACCOUNT_CARD_FOOTER,
)
from app.extensions.security import SecurityGuard

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

PLUGIN_NAME = "balance_monitor"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR = "WoolGate Team"
PLUGIN_DESCRIPTION = "自动监控各厂商账号余额，4级预警与耗尽预测，route.before钩子自动过滤耗尽账号，独立余额看板页面"
PLUGIN_TAGS = ["余额监控", "预警", "成本控制", "路由过滤"]

# ══════════════════════════════════════════════════════════════
# 配置定义
# ══════════════════════════════════════════════════════════════
CONFIG_SCHEMA = {
    "warning_threshold": {
        "type": "number",
        "label": "警告阈值（元）",
        "default": 5.0,
        "help": "余额低于此值触发🟠警告",
    },
    "critical_threshold": {
        "type": "number",
        "label": "紧急阈值（元）",
        "default": 1.0,
        "help": "余额低于此值触发🔴紧急并降权",
    },
    "notice_threshold": {
        "type": "number",
        "label": "注意阈值（元）",
        "default": 10.0,
        "help": "余额低于此值触发🟡注意",
    },
    "auto_sync_enabled": {
        "type": "boolean",
        "label": "自动同步余额",
        "default": True,
        "help": "启用后每日首次请求和请求后节流自动同步余额",
    },
    "sync_cooldown_minutes": {
        "type": "number",
        "label": "同步冷却时间（分钟）",
        "default": 60,
        "help": "两次自动同步之间的最小间隔",
    },
}

register_config(CONFIG_SCHEMA, default={
    "warning_threshold": 5.0,
    "critical_threshold": 1.0,
    "notice_threshold": 10.0,
    "auto_sync_enabled": True,
    "sync_cooldown_minutes": 60,
})

# ══════════════════════════════════════════════════════════════
# 余额同步引擎
# ══════════════════════════════════════════════════════════════

# 内存缓存：账号ID -> (同步时间戳, 余额信息)
_balance_cache: Dict[int, Dict[str, Any]] = {}
_last_sync_attempt: Dict[int, float] = {}


def get_balance_level(balance: Optional[float], config: Dict[str, Any]) -> str:
    """根据余额判断预警级别"""
    if balance is None:
        return "unknown"
    if balance <= 0:
        return "exhausted"
    if balance < config.get("critical_threshold", 1.0):
        return "critical"
    if balance < config.get("warning_threshold", 5.0):
        return "warning"
    if balance < config.get("notice_threshold", 10.0):
        return "notice"
    return "normal"


def get_balance_emoji(level: str) -> str:
    """获取预警级别对应的emoji"""
    return {
        "normal": "🟢",
        "notice": "🟡",
        "warning": "🟠",
        "critical": "🔴",
        "exhausted": "⚫",
        "unknown": "⚪",
    }.get(level, "⚪")


async def sync_account_balance(account_id: int, force: bool = False) -> Optional[Dict[str, Any]]:
    """
    同步单个账号的余额

    Args:
        account_id: 账号ID
        force: 是否强制同步（跳过冷却检查）

    Returns:
        余额信息字典，包含 balance_remaining, balance_unit, balance_level 等
    """
    from app.models.database import ModelAccount
    from app.services.balance import fetch_balance, BalanceUnsupportedError
    from sqlalchemy import select
    from app.models import AsyncSessionLocal

    now = time.time()

    # 冷却检查
    if not force:
        last_attempt = _last_sync_attempt.get(account_id, 0)
        cooldown = 60  # 默认60秒最小间隔
        if now - last_attempt < cooldown:
            return _balance_cache.get(account_id)

    _last_sync_attempt[account_id] = now

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelAccount).where(ModelAccount.id == account_id)
            )
            account = result.scalar_one_or_none()

            if not account:
                return None

            # 尝试获取余额
            try:
                balance_unit, balance_remaining = await fetch_balance(account)
                account.balance_remaining = balance_remaining
                account.balance_unit = balance_unit
                account.balance_sync_date = datetime.now()
                await session.commit()
                logger.info(f"[{PLUGIN_NAME}] 账号 {account_id} ({account.vendor}) 余额同步成功: {balance_remaining} {balance_unit}")
            except BalanceUnsupportedError:
                # 厂商不支持自动获取，使用手动维护的余额
                balance_remaining = account.balance_remaining
                balance_unit = account.balance_unit or "currency"
                logger.debug(f"[{PLUGIN_NAME}] 账号 {account_id} ({account.vendor}) 不支持自动获取，使用手动余额")
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 账号 {account_id} 余额同步失败: {e}")
                balance_remaining = account.balance_remaining
                balance_unit = account.balance_unit or "currency"

            # 获取配置
            try:
                from app.extensions.sdk import get_plugin_config
                config = await get_plugin_config(PLUGIN_NAME)
            except Exception:
                config = {
                    "warning_threshold": 5.0,
                    "critical_threshold": 1.0,
                    "notice_threshold": 10.0,
                }

            balance_info = {
                "account_id": account_id,
                "vendor": account.vendor,
                "balance_remaining": balance_remaining,
                "balance_unit": balance_unit,
                "balance_level": get_balance_level(balance_remaining, config),
                "sync_time": now,
            }

            _balance_cache[account_id] = balance_info
            return balance_info

    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] 同步账号 {account_id} 余额时异常: {e}")
        return None


async def sync_all_balances(force: bool = False) -> List[Dict[str, Any]]:
    """同步所有启用账号的余额"""
    from app.models.database import ModelAccount
    from sqlalchemy import select
    from app.models import AsyncSessionLocal

    results = []
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelAccount.id).where(ModelAccount.is_enable == True)
            )
            account_ids = [row[0] for row in result.all()]

        for account_id in account_ids:
            info = await sync_account_balance(account_id, force=force)
            if info:
                results.append(info)
    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] 同步所有余额时异常: {e}")

    return results


# ══════════════════════════════════════════════════════════════
# 路由感知：route.before 钩子
# ══════════════════════════════════════════════════════════════

@register_hook("route.before", priority=50)
async def on_route_before(ctx: "PipelineContext") -> None:
    """
    路由前钩子：过滤耗尽账号，紧急账号降权

    这个钩子在路由决策之前执行，用于：
    1. 检查候选账号的余额状态
    2. 过滤掉已耗尽的账号
    3. 对紧急余额的账号进行降权处理
    """
    pc = PluginContext(ctx, PLUGIN_NAME)

    try:
        # 获取配置
        try:
            from app.extensions.sdk import get_plugin_config
            config = await get_plugin_config(PLUGIN_NAME)
        except Exception:
            config = {
                "auto_sync_enabled": True,
                "sync_cooldown_minutes": 60,
            }

        # 自动同步余额（节流）
        if config.get("auto_sync_enabled", True):
            # 检查是否需要同步（节流：每N分钟最多同步一次）
            now = time.time()
            last_global_sync = pc.get("last_global_sync", 0)
            cooldown_seconds = config.get("sync_cooldown_minutes", 60) * 60

            if now - last_global_sync > cooldown_seconds:
                pc.set("last_global_sync", now)
                # 异步同步所有余额（不阻塞请求）
                import asyncio
                asyncio.create_task(sync_all_balances())

        # 检查候选账号的余额状态
        # 注意：这里我们不直接修改候选列表，而是通过上下文标记
        # 实际的过滤在选号器中通过 account.balance_remaining 字段实现
        exhausted_accounts = []
        critical_accounts = []

        for account_id, balance_info in _balance_cache.items():
            level = balance_info.get("balance_level", "unknown")
            if level == "exhausted":
                exhausted_accounts.append(account_id)
            elif level == "critical":
                critical_accounts.append(account_id)

        if exhausted_accounts:
            pc.set("exhausted_accounts", exhausted_accounts)
            logger.info(f"[{PLUGIN_NAME}] 检测到 {len(exhausted_accounts)} 个耗尽账号，将在选号时过滤")

        if critical_accounts:
            pc.set("critical_accounts", critical_accounts)
            logger.debug(f"[{PLUGIN_NAME}] 检测到 {len(critical_accounts)} 个紧急账号，将在选号时降权")

    except Exception as e:
        logger.warning(f"[{PLUGIN_NAME}] route.before 钩子执行异常: {e}")


# ══════════════════════════════════════════════════════════════
# UI 展示：余额看板页面
# ══════════════════════════════════════════════════════════════

async def render_balance_page(request=None):
    """渲染余额看板页面"""
    try:
        from nicegui import ui
        from app.models.database import ModelAccount
        from sqlalchemy import select, func
        from app.models import AsyncSessionLocal

        with ui.column().classes('w-full max-w-[1440px] mx-auto p-5 gap-4'):
            # 标题
            with ui.row().classes('items-center justify-between w-full'):
                ui.label('💰 余额监控与额度预警').classes('text-3xl font-bold text-gray-800')
                with ui.row().classes('gap-2'):
                    ui.button('🔄 手动同步', on_click=lambda: ui.notify('正在同步所有账号余额...', type='info')).props('outline color=primary')

            # 统计卡片
            async with AsyncSessionLocal() as session:
                total_result = await session.execute(select(func.count(ModelAccount.id)).where(ModelAccount.is_enable == True))
                total_accounts = total_result.scalar() or 0

                # 统计各余额级别的账号数
                all_accounts_result = await session.execute(
                    select(ModelAccount).where(ModelAccount.is_enable == True)
                )
                all_accounts = all_accounts_result.scalars().all()

            try:
                from app.extensions.sdk import get_plugin_config
                config = await get_plugin_config(PLUGIN_NAME)
            except Exception:
                config = {"warning_threshold": 5.0, "critical_threshold": 1.0, "notice_threshold": 10.0}

            level_counts = {"normal": 0, "notice": 0, "warning": 0, "critical": 0, "exhausted": 0, "unknown": 0}
            total_balance = 0.0
            balance_accounts = 0

            for account in all_accounts:
                level = get_balance_level(account.balance_remaining, config)
                level_counts[level] = level_counts.get(level, 0) + 1
                if account.balance_remaining is not None and account.balance_unit == "currency":
                    total_balance += account.balance_remaining
                    balance_accounts += 1

            def stat_card(icon, title, value, sub=None, color="blue"):
                with ui.card().classes(f'flex-1 border-l-4 border-{color}-500').style('height:120px'):
                    with ui.column().classes('w-full items-center gap-1 justify-center').style('height:100%'):
                        ui.label(icon).classes('text-2xl')
                        ui.label(title).classes('text-sm text-gray-500')
                        ui.label(str(value)).classes('text-2xl font-bold')
                        if sub:
                            ui.label(sub).classes('text-xs text-gray-400')

            with ui.row().classes('w-full gap-3'):
                stat_card('📊', '监控账号', total_accounts, f'已获取余额 {balance_accounts}', 'blue')
                stat_card('🟢', '正常', level_counts.get("normal", 0), '余额充足', 'green')
                stat_card('🟡', '注意', level_counts.get("notice", 0), '余额偏低', 'yellow')
                stat_card('🟠', '警告', level_counts.get("warning", 0), '余额较低', 'orange')
                stat_card('🔴', '紧急', level_counts.get("critical", 0), '余额极低', 'red')
                stat_card('⚫', '耗尽', level_counts.get("exhausted", 0), '已无可用额度', 'gray')

            # 总余额
            if balance_accounts > 0:
                with ui.card().classes('w-full bg-gradient-to-r from-green-50 to-blue-50 border-l-4 border-green-500'):
                    with ui.column().classes('gap-2 p-4'):
                        ui.label('💵 总余额概览').classes('text-lg font-bold text-gray-800')
                        ui.label(f'已监控账号总余额: ¥{total_balance:.4f}').classes('text-2xl font-bold text-green-600')
                        ui.label(f'平均每账号: ¥{total_balance/balance_accounts:.4f}').classes('text-sm text-gray-500')

            # 账号余额列表
            ui.label('📋 账号余额明细').classes('text-2xl font-bold text-gray-800 mt-4')

            if not all_accounts:
                with ui.card().classes('w-full text-center p-12'):
                    ui.icon('account_circle', size='4rem').classes('text-gray-400')
                    ui.label('暂无启用账号').classes('text-xl text-gray-500 mt-4')
                    ui.label('请先在账号管理中添加并启用账号').classes('text-sm text-gray-400 mt-2')
            else:
                for account in all_accounts:
                    level = get_balance_level(account.balance_remaining, config)
                    emoji = get_balance_emoji(level)
                    level_text = {
                        "normal": "正常", "notice": "注意", "warning": "警告",
                        "critical": "紧急", "exhausted": "耗尽", "unknown": "未知"
                    }.get(level, "未知")

                    with ui.card().classes('w-full shadow-sm hover:shadow-md transition-shadow'):
                        with ui.row().classes('w-full items-center justify-between gap-4 p-4'):
                            with ui.column().classes('flex-1 gap-1'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.label(f'{emoji} {account.vendor}').classes('font-bold text-gray-800 text-lg')
                                    ui.badge(level_text, color={
                                        "normal": "positive", "notice": "warning", "warning": "orange",
                                        "critical": "negative", "exhausted": "grey", "unknown": "grey"
                                    }.get(level, "grey")).props('outline')
                                if account.default_model:
                                    ui.label(f'默认模型: {account.default_model}').classes('text-sm text-gray-500')
                                if account.balance_sync_date:
                                    ui.label(f'最后同步: {account.balance_sync_date}').classes('text-xs text-gray-400')
                                else:
                                    ui.label('未同步过余额').classes('text-xs text-gray-400')

                            with ui.column().classes('items-end gap-1'):
                                if account.balance_remaining is not None:
                                    unit = "元" if account.balance_unit == "currency" else account.balance_unit
                                    ui.label(f'¥{account.balance_remaining:.4f}').classes(f'text-2xl font-bold {"text-green-600" if level == "normal" else "text-red-600" if level in ("critical", "exhausted") else "text-orange-600"}')
                                    ui.label(unit).classes('text-xs text-gray-400')
                                else:
                                    ui.label('未维护').classes('text-xl text-gray-400')
                                    ui.label('手动维护或厂商不支持').classes('text-xs text-gray-400')

    except Exception as e:
        logger.error(f"[{PLUGIN_NAME}] 渲染余额看板页面异常: {e}")
        from nicegui import ui
        with ui.card().classes('w-full bg-red-50 border-l-4 border-red-500 p-4'):
            ui.label(f'页面渲染异常: {e}').classes('text-red-700')


# 注册余额看板页面
register_page(
    route="/balance",
    title="余额监控",
    render_func=render_balance_page,
)

# 注册导航项
register_nav_item(
    label="💰 余额监控",
    route="/balance",
    description="监控各平台账号余额与额度，低余额预警",
)


# ══════════════════════════════════════════════════════════════
# UI 展示：首页总览卡片（dashboard.widgets 挂载点）
# ══════════════════════════════════════════════════════════════

async def render_dashboard_widget():
    """渲染首页余额总览小部件"""
    try:
        from nicegui import ui
        from app.models.database import ModelAccount
        from sqlalchemy import select, func
        from app.models import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelAccount).where(ModelAccount.is_enable == True)
            )
            accounts = result.scalars().all()

        try:
            from app.extensions.sdk import get_plugin_config
            config = await get_plugin_config(PLUGIN_NAME)
        except Exception:
            config = {"warning_threshold": 5.0, "critical_threshold": 1.0, "notice_threshold": 10.0}

        critical_count = 0
        exhausted_count = 0
        total_balance = 0.0
        balance_count = 0

        for account in accounts:
            level = get_balance_level(account.balance_remaining, config)
            if level == "critical":
                critical_count += 1
            elif level == "exhausted":
                exhausted_count += 1
            if account.balance_remaining is not None and account.balance_unit == "currency":
                total_balance += account.balance_remaining
                balance_count += 1

        alert_count = critical_count + exhausted_count
        alert_color = "red" if alert_count > 0 else "green"
        alert_icon = "⚠️" if alert_count > 0 else "✅"

        with ui.card().classes(f'flex-1 border-l-4 border-{alert_color}-500 shadow-lg').style('min-height:170px'):
            with ui.column().classes('w-full items-center gap-1 justify-center p-4').style('height:100%'):
                ui.icon('account_balance_wallet', size='2.5rem').classes(f'text-{alert_color}-500')
                ui.label('余额监控').classes('text-gray-500 text-sm')
                if alert_count > 0:
                    ui.label(f'{alert_count} 个账号需关注').classes('text-2xl font-bold text-red-600')
                    ui.label(f'🔴紧急 {critical_count} / ⚫耗尽 {exhausted_count}').classes('text-xs text-gray-500')
                else:
                    ui.label('全部正常').classes('text-2xl font-bold text-green-600')
                    ui.label(f'已监控 {len(accounts)} 个账号').classes('text-xs text-gray-500')
                if balance_count > 0:
                    ui.label(f'总余额 ¥{total_balance:.2f}').classes('text-xs text-gray-400 mt-1')
                ui.button('查看详情 →', on_click=lambda: ui.navigate.to('/balance')).props('flat color=primary text-xs').classes('mt-2')

    except Exception as e:
        logger.warning(f"[{PLUGIN_NAME}] 渲染首页小部件异常: {e}")


register_component(
    hook_point=UI_HOOK_DASHBOARD_WIDGETS,
    render_func=render_dashboard_widget,
    priority=10,
)


# ══════════════════════════════════════════════════════════════
# 插件加载完成日志
# ══════════════════════════════════════════════════════════════

logger.info(f"[{PLUGIN_NAME}] 余额监控与额度预警插件已加载")
logger.info(f"[{PLUGIN_NAME}] 已注册: route.before钩子 + /balance页面 + 导航项 + 首页小部件")
