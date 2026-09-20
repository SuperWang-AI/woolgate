"""
WoolGate 主应用
LLM多账号免费额度智能调度网关
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.models import init_database
from app.routes.api import router as api_router
from app.services.scheduler import start_scheduler, stop_scheduler
from app.ui.admin import init_ui

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 版本号（统一入口，开源发布前确定正式版本）
VERSION = "0.7.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("=" * 60)
    logger.info("WoolGate 启动中...")
    logger.info("=" * 60)
    
    # 验证必需配置
    try:
        settings.validate_required()
    except ValueError as e:
        logger.error(f"配置验证失败: {e}")
        logger.error("请检查.env文件配置")
        raise
    
    # 初始化数据库
    await init_database()

    # 初始化模型能力清单（M4 LLM 智能路由用）
    try:
        from app.models import AsyncSessionLocal
        from app.services.model_catalog_service import ModelCatalogService
        from app.services.embedding import EmbeddingService
        from app.pipeline.config import PipelineConfig
        from app.models.database import ModelAccount
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            catalog_svc = ModelCatalogService(session)
            # 确保所有启用账号的模型都在目录中
            result = await session.execute(
                select(ModelAccount).where(ModelAccount.is_enable == True)  # noqa: E712
            )
            accounts = result.scalars().all()
            for account in accounts:
                await catalog_svc.ensure_model(account.model_name, account.vendor, account_id=account.id)
            logger.info(f"模型能力清单初始化完成: {len(accounts)} 个模型")

            # 异步触发模型能力向量重算（不阻塞启动；仅重算缺失向量的模型，避免每次启动全量白烧外部 API 额度）
            try:
                import asyncio

                async def _recompute_model_embeddings_async():
                    try:
                        async with AsyncSessionLocal() as s:
                            cfg = await PipelineConfig.load(s)
                            embed_svc = EmbeddingService(cfg.router_config, db=s)
                            cs = ModelCatalogService(s)
                            await cs.recompute_missing_embeddings(embed_svc)
                    except Exception as e:
                        logger.warning(f"模型能力向量重算失败: {e}")

                asyncio.create_task(_recompute_model_embeddings_async())
                logger.info("模型能力向量增量重算任务已启动（仅缺失向量）")
            except Exception as e:
                logger.warning(f"模型能力向量重算启动失败（不影响启动）: {e}")
    except Exception as e:
        logger.warning(f"模型能力清单初始化失败（不影响启动）: {e}")

    # 初始化默认 API Key（M3 企业化部署）
    try:
        from app.models import AsyncSessionLocal
        from app.models.database import ApiKey
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.api_key == settings.GATEWAY_BEARER_TOKEN)
            )
            existing = result.scalar_one_or_none()
            if not existing:
                default_key = ApiKey(
                    api_key=settings.GATEWAY_BEARER_TOKEN,
                    name="默认全局Key（兼容旧版，自动路由）",
                    default_model=None,   # None=向量/LLM 路由自动选择
                    is_active=True,
                )
                session.add(default_key)
                await session.commit()
                logger.info("默认 API Key 初始化完成")
    except Exception as e:
        logger.warning(f"默认 API Key 初始化失败（不影响启动）: {e}")

    # 启动定时任务
    start_scheduler()
    
    logger.info(f"服务已启动: http://{settings.HOST}:{settings.PORT}")
    logger.info(f"API文档: http://{settings.HOST}:{settings.PORT}/docs")
    logger.info(f"管理界面: http://{settings.HOST}:{settings.PORT}/admin")
    
    yield
    
    # 关闭时
    logger.info("WoolGate 正在关闭...")
    stop_scheduler()
    logger.info("服务已停止")


# 创建FastAPI应用
app = FastAPI(
    title="WoolGate",
    description="LLM多账号免费额度智能调度网关",
    version=VERSION,
    lifespan=lifespan
)

# CORS配置（仅内网使用；不带凭证，避免 * + credentials 组合不规范）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, tags=["OpenAI Compatible API"])

# 加载插件（必须在 init_ui 之前，因为插件会注册页面/导航/组件，create_ui 需要读取这些注册表）
try:
    from app.extensions.loader import load_plugins
    loaded = load_plugins()
    if loaded:
        logger.info(f"已加载插件: {', '.join(loaded)}")
except Exception as e:
    logger.warning(f"插件加载失败（不影响启动）: {e}")

# 挂载 NiceGUI 管理界面
init_ui(app)


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "WoolGate",
        "version": VERSION,
        "description": "LLM多账号免费额度智能调度网关",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "models": "/v1/models",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False
    )
