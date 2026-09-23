"""
管理后台工具函数
所有与业务无关的通用工具函数都放在这里
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta


def format_local_time(dt: datetime | None) -> str:
    """将 UTC 时间格式化为本地时间字符串"""
    if not dt:
        return "-"
    # TODO: 从 admin.py 迁移
    return ""


def get_today_start_utc() -> datetime:
    """获取今天 00:00 的 UTC 时间"""
    # TODO: 从 admin.py 迁移
    return datetime.now(timezone.utc)


def vendor_icon_html(icon: str, cls: str = "w-8 h-8 rounded object-contain") -> str:
    """生成厂商图标的 HTML"""
    # TODO: 从 admin.py 迁移
    return ""
