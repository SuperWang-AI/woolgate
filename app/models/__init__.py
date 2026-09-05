"""
数据库初始化和连接管理
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from app.models.database import Base, SystemConfig
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# 创建异步引擎（WAL模式优化并发，NullPool每次请求独立连接，避免StaticPool单连接被关闭后失效）
engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={
        "check_same_thread": False,
    },
    poolclass=NullPool,
)

# 会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def _ensure_columns(conn):
    """轻量迁移：为已存在的表补充新增列（幂等）"""
    from sqlalchemy import text

    # ── model_account 补列 ──
    result = await conn.execute(text("PRAGMA table_info(model_account)"))
    cols = {row[1] for row in result.fetchall()}
    migrations = [
        ("balance_remaining", "FLOAT"),
        ("balance_unit", "VARCHAR(20)"),
        ("balance_sync_date", "VARCHAR(10)"),
        ("daily_used_tokens", "INTEGER DEFAULT 0"),
        ("daily_used_currency", "FLOAT DEFAULT 0.0"),
        ("total_used_currency", "FLOAT DEFAULT 0.0"),
        ("tenant_id", "VARCHAR(64)"),
    ]
    for col, coltype in migrations:
        if col not in cols:
            await conn.execute(text(f"ALTER TABLE model_account ADD COLUMN {col} {coltype}"))
            logger.info(f"迁移: model_account 增加列 {col}")

    # ── system_config 补列（M1 架构重构）──
    result = await conn.execute(text("PRAGMA table_info(system_config)"))
    cols = {row[1] for row in result.fetchall()}
    sys_migrations = [
        ("router_strategy", "VARCHAR(20) DEFAULT 'off'"),
        ("router_config_json", "JSON"),
        ("selector_strategy", "VARCHAR(20) DEFAULT 'pin'"),
        ("selector_config_json", "JSON"),
        ("context_strategy", "VARCHAR(20) DEFAULT 'passthrough'"),
        ("context_config_json", "JSON"),
        ("tenant_enabled", "BOOLEAN DEFAULT 0"),
        ("budget_enabled", "BOOLEAN DEFAULT 0"),
        ("edition", "VARCHAR(20) DEFAULT 'opensource'"),
    ]
    for col, coltype in sys_migrations:
        if col not in cols:
            await conn.execute(text(f"ALTER TABLE system_config ADD COLUMN {col} {coltype}"))
            logger.info(f"迁移: system_config 增加列 {col}")

    # ── request_log 补列（M1 观测埋点）──
    result = await conn.execute(text("PRAGMA table_info(request_log)"))
    cols = {row[1] for row in result.fetchall()}
    log_migrations = [
        ("request_id", "VARCHAR(64)"),
        ("domain_tag", "VARCHAR(50)"),
        ("router_strategy", "VARCHAR(20)"),
        ("selector_strategy", "VARCHAR(20)"),
        ("context_strategy", "VARCHAR(20)"),
        ("switch_count", "INTEGER DEFAULT 0"),
        ("summary_used", "BOOLEAN DEFAULT 0"),
        ("tenant_id", "VARCHAR(64)"),
    ]
    for col, coltype in log_migrations:
        if col not in cols:
            await conn.execute(text(f"ALTER TABLE request_log ADD COLUMN {col} {coltype}"))
            logger.info(f"迁移: request_log 增加列 {col}")

    # ── domain_prototype 补列（M3 多示例平均向量）──
    result = await conn.execute(text("PRAGMA table_info(domain_prototype)"))
    cols = {row[1] for row in result.fetchall()}
    domain_migrations = [
        ("examples", "JSON"),
    ]
    for col, coltype in domain_migrations:
        if col not in cols:
            await conn.execute(text(f"ALTER TABLE domain_prototype ADD COLUMN {col} {coltype}"))
            logger.info(f"迁移: domain_prototype 增加列 {col}")


async def init_database():
    """初始化数据库（创建表 + 轻量迁移 + 默认配置）"""
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        # 轻量迁移（已有表补充新列）
        await _ensure_columns(conn)
        
        # 启用WAL模式
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        
    logger.info("数据库表创建完成")
    
    # 初始化默认系统配置
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(SystemConfig))
        config = result.scalar_one_or_none()
        
        if not config:
            config = SystemConfig(id=1)
            session.add(config)
            await session.commit()
            logger.info("系统默认配置初始化完成")


async def get_db():
    """依赖注入：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
