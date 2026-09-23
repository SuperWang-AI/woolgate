"""
管理后台数据服务层
所有数据库查询和业务逻辑计算都放在这里
不依赖任何 UI 组件，可独立测试
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, func, case, desc
from datetime import datetime, timedelta, timezone

from app.models import AsyncSessionLocal
from app.models.database import SystemConfig, ModelAccount, RequestLog
# 时间工具函数
CN_TZ = timezone(timedelta(hours=8))

def get_today_start_utc():
    """本地今天 00:00 对应的 UTC 时间（naive），用于按本地日统计"""
    local_midnight = datetime.now(CN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


# ========== 仪表盘数据 ==========

async def get_stats() -> dict:
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


async def get_trend_data(days: int = 7) -> dict:
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


# ========== 账号管理 ==========

async def get_accounts() -> list:
    """获取所有账号列表（启用的排在前面）"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelAccount).order_by(desc(ModelAccount.is_enable), desc(ModelAccount.id))
        )
        return result.scalars().all()


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


# ========== 系统配置保存 ==========

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


# ========== 启动引导配置 ==========

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
    
    return data, profile_name


# ========== 启动引导应用 ==========

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


# ========== 启动引导判断 ==========

async def needs_onboard(request=None) -> bool:
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
