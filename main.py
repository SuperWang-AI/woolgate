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

    # 初始化预置领域（M2 向量路由用，M3 多示例平均向量）
    try:
        from app.models import AsyncSessionLocal
        from app.services.domain_service import DomainService
        from app.services.embedding import EmbeddingService
        from app.pipeline.config import RouterConfig
        async with AsyncSessionLocal() as session:
            domain_svc = DomainService(session)
            # 先确保领域存在（补充 examples）
            await domain_svc.ensure_default_domains(embedding_service=None)
            # 异步触发向量重算（多示例平均，不阻塞启动，使用独立会话）
            try:
                from app.pipeline.config import PipelineConfig
                import asyncio

                async def _recompute_embeddings_async():
                    try:
                        async with AsyncSessionLocal() as s:
                            cfg = await PipelineConfig.load(s)
                            embed_svc = EmbeddingService(cfg.router_config, db=s)
                            ds = DomainService(s)
                            await ds.recompute_all_embeddings(embed_svc)
                    except Exception as e:
                        logger.warning(f"领域向量重算失败: {e}")

                asyncio.create_task(_recompute_embeddings_async())
                logger.info("领域向量重算任务已启动（多示例平均）")
            except Exception as e:
                logger.warning(f"领域向量重算启动失败（不影响启动）: {e}")
        logger.info("预置领域初始化完成")
    except Exception as e:
        logger.warning(f"预置领域初始化失败（不影响启动）: {e}")

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
                    default_domain=None,   # None=向量路由自动判断
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
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置（仅内网使用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, tags=["OpenAI Compatible API"])

# 挂载 NiceGUI 管理界面
init_ui(app)


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "WoolGate",
        "version": "1.0.0",
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
