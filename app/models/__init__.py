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
        ("onboarded", "BOOLEAN DEFAULT 0"),
        ("onboard_profile", "VARCHAR(100)"),
        ("virtual_entry_name", "VARCHAR(50) DEFAULT 'woolgate'"),
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
        ("session_id", "VARCHAR(64)"),
        ("domain_tag", "VARCHAR(50)"),
        ("router_strategy", "VARCHAR(20)"),
        ("selector_strategy", "VARCHAR(20)"),
        ("context_strategy", "VARCHAR(20)"),
        ("switch_count", "INTEGER DEFAULT 0"),
        ("summary_used", "BOOLEAN DEFAULT 0"),
        ("tenant_id", "VARCHAR(64)"),
        ("user_feedback", "VARCHAR(20)"),
        ("feedback_at", "DATETIME"),
        ("implicit_signal", "VARCHAR(50)"),
        # ── C5 学习型路由：成本/决策明细/分类引擎 ──
        ("estimated_cost", "FLOAT DEFAULT 0.0"),
        ("actual_cost", "FLOAT DEFAULT 0.0"),
        ("router_decision", "VARCHAR(100)"),
        ("selector_decision", "VARCHAR(100)"),
        ("classify_engine", "VARCHAR(20)"),
        ("degraded", "BOOLEAN DEFAULT 0"),
        ("degrade_reason", "VARCHAR(100)"),
    ]
    for col, coltype in log_migrations:
        if col not in cols:
            await conn.execute(text(f"ALTER TABLE request_log ADD COLUMN {col} {coltype}"))
            logger.info(f"迁移: request_log 增加列 {col}")

    # ── model_catalog 补列（M4 LLM 智能路由）──
    result = await conn.execute(text("PRAGMA table_info(model_catalog)"))
    cols = {row[1] for row in result.fetchall()}
    catalog_migrations = [
        ("capability_description", "TEXT"),
        ("avg_latency", "FLOAT"),
        ("embedding_vector", "JSON"),
        ("examples", "JSON"),
    ]
    for col, coltype in catalog_migrations:
        if col not in cols:
            await conn.execute(text(f"ALTER TABLE model_catalog ADD COLUMN {col} {coltype}"))
            logger.info(f"迁移: model_catalog 增加列 {col}")

    # ── api_key 补列（M4 default_domain → default_model）──
    result = await conn.execute(text("PRAGMA table_info(api_key)"))
    cols = {row[1] for row in result.fetchall()}
    if "default_model" not in cols:
        await conn.execute(text("ALTER TABLE api_key ADD COLUMN default_model VARCHAR(100)"))
        logger.info("迁移: api_key 增加列 default_model")

    # ── M4 清理：删除废弃的领域表（如果存在）──
    for table in ["domain_prototype", "domain_model_mapping"]:
        result = await conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"))
        if result.fetchone():
            await conn.execute(text(f"DROP TABLE {table}"))
            logger.info(f"M4 清理: 删除废弃表 {table}")

    # ── session_state 迁移：current_domain → current_model ──
    result = await conn.execute(text("PRAGMA table_info(session_state)"))
    cols = {row[1] for row in result.fetchall()}
    if "current_domain" in cols and "current_model" not in cols:
        # SQLite 不支持直接删列，用重建表方式
        await conn.execute(text("ALTER TABLE session_state ADD COLUMN current_model VARCHAR(100)"))
        await conn.execute(text("UPDATE session_state SET current_model = current_domain"))
        logger.info("迁移: session_state current_domain → current_model")
    elif "current_model" not in cols:
        await conn.execute(text("ALTER TABLE session_state ADD COLUMN current_model VARCHAR(100)"))
        logger.info("迁移: session_state 增加列 current_model")


async def init_database():
    """初始化数据库（创建表 + 轻量迁移 + 默认配置）"""
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        # 轻量迁移（已有表补充新列）
        await _ensure_columns(conn)
        
        # 不使用 WAL 模式：OrbStack/虚拟化挂载卷上 WAL 的 mmap/shm 不稳定，
        # 会引发 disk I/O error；保持默认 rollback journal（DELETE）模式更稳。
        # 如需并发优化，改用连接池参数而非 WAL。
        
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
