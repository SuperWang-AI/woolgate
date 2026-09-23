"""
管理后台数据服务层
所有数据库查询和业务逻辑计算都放在这里
不依赖任何 UI 组件，可独立测试
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncSessionLocal
from app.models.database import SystemConfig


# ========== 仪表盘数据 ==========

async def get_stats(db: AsyncSession) -> dict:
    """获取首页统计数据"""
    # TODO: 从 admin.py 迁移
    return {}


async def get_trend_data(db: AsyncSession, days: int = 7) -> list:
    """获取请求趋势数据"""
    # TODO: 从 admin.py 迁移
    return []


# ========== 账号管理 ==========

async def get_accounts(db: AsyncSession) -> list:
    """获取账号列表"""
    # TODO: 从 admin.py 迁移
    return []


# ========== 系统配置 ==========

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


async def save_system_config(config_data: dict) -> bool:
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


# ========== 向导 ==========

def build_onboarding_data(answers: dict) -> dict:
    """根据向导答案构建配置数据"""
    # TODO: 从 admin.py 迁移
    return {}


async def apply_onboard_profile(db: Session, answers: dict):
    """应用向导配置"""
    # TODO: 从 admin.py 迁移
    pass


# ========== 请求日志 ==========

async def get_log_stats():
    """获取日志统计数据"""
    from sqlalchemy import func, select, desc
    from app.models import AsyncSessionLocal
    from app.models.database import RequestLog
    
    async with AsyncSessionLocal() as session:
        # 查询统计数据（全部）
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

        return {
            'total_count': total_count,
            'success_count': success_count,
            'failed_count': failed_count,
            'total_prompt': total_prompt,
            'total_completion': total_completion,
        }


async def get_recent_logs(limit: int = 50):
    """获取最近的日志"""
    from sqlalchemy import select, desc
    from app.models import AsyncSessionLocal
    from app.models.database import RequestLog
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RequestLog)
            .order_by(desc(RequestLog.created_at))
            .limit(limit)
        )
        return result.scalars().all()


# ========== 账号管理 ==========

async def get_accounts():
    """获取账号列表"""
    from sqlalchemy import select
    from app.models import AsyncSessionLocal
    from app.models.database import ModelAccount
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ModelAccount))
        return result.scalars().all()


async def get_account_models():
    """获取账号模型清单（按 account_id 聚合）"""
    from sqlalchemy import select
    from app.models import AsyncSessionLocal
    from app.models.database import ModelCatalog
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ModelCatalog))
        account_models = {}
        for cat in result.scalars().all():
            account_models.setdefault(cat.account_id, []).append(cat)
        return account_models
