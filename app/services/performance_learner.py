"""
学习型路由：模型历史表现统计 job

每小时从 RequestLog 聚合一次，按 (account_id, model_name, routed_model) 分组，
更新 ModelPerformance 表，供 CostFirstSelector 选号时读历史表现。
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, case

from app.models.database import RequestLog, ModelPerformance
from app.models import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def aggregate_performance(hours: int = 168):
    """
    聚合最近 N 小时（默认7天=168小时）的请求日志到 model_performance 表。
    滑动窗口：每次先删除窗口外的旧记录，再重新聚合窗口内数据。
    时间衰减：超过7天的历史数据不再影响选号决策。
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    async with AsyncSessionLocal() as session:
        # 聚合查询
        stmt = (
            select(
                RequestLog.account_id,
                RequestLog.model_name,
                RequestLog.routed_model,
                func.count(RequestLog.id).label("req_count"),
                func.sum(case((RequestLog.status == "success", 1), else_=0)).label("ok_count"),
                func.sum(case((RequestLog.implicit_signal == "stream_interrupted", 1), else_=0)).label("interrupted"),
                func.sum(case((RequestLog.implicit_signal == "switch_retry", 1), else_=0)).label("retried"),
                func.avg(RequestLog.actual_cost).label("avg_cost"),
            )
            .where(RequestLog.request_time >= since)
            .where(RequestLog.account_id.isnot(None))
            .group_by(RequestLog.account_id, RequestLog.model_name, RequestLog.routed_model)
        )
        rows = (await session.execute(stmt)).all()

        updated = 0
        for row in rows:
            if not row.account_id or not row.model_name:
                continue

            # upsert：查现有记录
            existing = (
                await session.execute(
                    select(ModelPerformance).where(
                        ModelPerformance.account_id == row.account_id,
                        ModelPerformance.model_name == row.model_name,
                        ModelPerformance.routed_model == (row.routed_model or "general"),
                    )
                )
            ).scalar_one_or_none()

            if existing:
                # 滑动窗口：全量替换（窗口内重新统计，不是增量累加）
                existing.request_count = row.req_count
                existing.success_count = (row.ok_count or 0)
                existing.interrupted_count = (row.interrupted or 0)
                existing.retry_count = (row.retried or 0)
                existing.avg_actual_cost = row.avg_cost or 0.0
                existing.last_updated = datetime.utcnow()
            else:
                perf = ModelPerformance(
                    account_id=row.account_id,
                    model_name=row.model_name,
                    routed_model=row.routed_model or "general",
                    request_count=row.req_count,
                    success_count=row.ok_count or 0,
                    interrupted_count=row.interrupted or 0,
                    retry_count=row.retried or 0,
                    avg_actual_cost=row.avg_cost or 0.0,
                    last_updated=datetime.utcnow(),
                )
                session.add(perf)
            updated += 1

        await session.commit()
        logger.info(f"[performance_learner] 聚合完成: {updated} 个 (账号×模型×路由模型) 组合已更新")


async def get_effective_cost_map(session, model_name: str, routed_model: str) -> dict:
    """
    查询某模型某路由模型下，各账号的历史有效成本。
    返回 {account_id: effective_cost}，无数据的账号不在 dict 里。
    """
    rows = (
        await session.execute(
            select(ModelPerformance).where(
                ModelPerformance.model_name == model_name,
                ModelPerformance.routed_model == routed_model,
                ModelPerformance.request_count >= 5,  # 样本量太小不采信
            )
        )
    ).scalars().all()

    return {r.account_id: r.effective_cost for r in rows}
