"""
定时任务调度
负责每日额度重置、日志清理等周期性任务
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import logging
import pytz

from app.models import AsyncSessionLocal
from app.models.database import ModelAccount, RequestLog, SystemConfig
from sqlalchemy import select, delete

logger = logging.getLogger(__name__)

# 全局调度器
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Shanghai"))


async def reset_daily_quota():
    """每日00:00重置当日本地用量统计（daily_used_*）"""
    logger.info("开始执行每日用量重置任务")
    
    async with AsyncSessionLocal() as session:
        # 查询所有启用账号
        result = await session.execute(
            select(ModelAccount).where(ModelAccount.is_enable == True)
        )
        accounts = result.scalars().all()
        
        reset_count = 0
        for account in accounts:
            # 重置当日本地用量（预计余额 = 初始额度 - 当日用量）
            account.daily_used_tokens = 0
            account.daily_used_currency = 0.0
            
            # 清除冷却状态
            account.cool_down_until = None
            
            reset_count += 1
        
        await session.commit()
        logger.info(f"每日用量重置完成，共重置 {reset_count} 个账号")


async def clean_old_logs():
    """清理过期日志"""
    logger.info("开始执行日志清理任务")
    
    async with AsyncSessionLocal() as session:
        # 获取日志保留天数配置
        result = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
        config = result.scalar_one_or_none()
        
        if not config:
            logger.warning("系统配置不存在，跳过日志清理")
            return
        
        # 计算截止日期
        cutoff_date = datetime.utcnow() - timedelta(days=config.log_retention_days)
        
        # 删除过期日志
        result = await session.execute(
            delete(RequestLog)
            .where(RequestLog.created_at < cutoff_date)
        )
        
        await session.commit()
        deleted_count = result.rowcount
        logger.info(f"日志清理完成，删除 {deleted_count} 条过期日志")


def start_scheduler():
    """启动定时任务调度器"""
    
    # 每日00:00执行额度重置
    scheduler.add_job(
        reset_daily_quota,
        trigger=CronTrigger(hour=0, minute=0, timezone="Asia/Shanghai"),
        id="reset_daily_quota",
        name="每日额度重置",
        replace_existing=True
    )
    
    # 每天凌晨3点执行日志清理
    scheduler.add_job(
        clean_old_logs,
        trigger=CronTrigger(hour=3, minute=0, timezone="Asia/Shanghai"),
        id="clean_old_logs",
        name="清理过期日志",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("定时任务调度器已启动")


def stop_scheduler():
    """停止定时任务调度器"""
    scheduler.shutdown()
    logger.info("定时任务调度器已停止")
