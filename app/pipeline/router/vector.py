"""
向量路由策略（vector）—— M4 重构后

通过 embedding 余弦相似度匹配模型能力向量，高置信度直接选模型。
低置信度时返回 None，由上层升级到 LLM 智能路由。

核心变化（M4）：
- 不再匹配领域向量，直接匹配模型能力向量
- 不再有"领域"概念，路由结果直接是模型名
- 斜杠命令从指定领域改为指定模型（/qwen-plus）
- 滞回逻辑从领域滞回改为模型滞回
- 高置信度（>= threshold_high）直接用，低置信度返回 None 升级到 LLM
"""
import logging
import time
from typing import TYPE_CHECKING, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.router.base import ModelRouter
from app.services.embedding import EmbeddingService, cosine_similarity
from app.services.model_catalog import ModelCatalogService
from app.models.database import ModelCatalog

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext
    from app.pipeline.config import RouterConfig

logger = logging.getLogger(__name__)


class VectorRouter(ModelRouter):
    """向量路由：embedding 相似度匹配模型能力向量"""

    name = "vector"

    def __init__(self, config: "RouterConfig", db: Optional[AsyncSession] = None):
        self.config = config
        self.db = db
        self._embedding_service: Optional[EmbeddingService] = None
        self._last_user_vector: Optional[List[float]] = None

    def _get_embedding_service(self) -> EmbeddingService:
        """懒加载 EmbeddingService"""
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService(self.config, db=self.db)
        return self._embedding_service

    async def route(self, ctx: "PipelineContext") -> None:
        """执行向量路由决策"""
        start = time.time()
        ctx.router_strategy = self.name

        if self.db is None:
            ctx.target_model = self.config.fallback_model
            ctx.router_decision = "vector: 无数据库会话，使用 fallback"
            logger.warning("[vector-router] 无 db 会话，回退 fallback_model")
            ctx.router_latency_ms = int((time.time() - start) * 1000)
            return

        try:
            # 0. 斜杠命令强制指定模型（最高优先级）
            if ctx.forced_model:
                ctx.target_model = ctx.forced_model
                ctx.router_decision = f"vector: 斜杠命令强制模型={ctx.forced_model}"
                logger.info(f"[vector-router] 斜杠命令强制: 模型={ctx.forced_model}")
                ctx.router_latency_ms = int((time.time() - start) * 1000)
                return

            # 1. 提取最新用户消息
            user_text = self._extract_latest_user_message(ctx.original_messages)
            if not user_text:
                # 无用户消息时，使用默认模型或 fallback
                target_model = ctx.default_model or self.config.fallback_model
                ctx.target_model = target_model
                ctx.router_decision = f"vector: 无用户消息，使用默认模型={target_model}"
                ctx.router_latency_ms = int((time.time() - start) * 1000)
                return

            # 2. 计算用户消息向量
            embed_svc = self._get_embedding_service()
            user_vector = await embed_svc.embed(user_text)
            self._last_user_vector = user_vector
            if not user_vector:
                target_model = ctx.default_model or self.config.fallback_model
                ctx.target_model = target_model
                ctx.router_decision = f"vector: embedding 失败，使用默认模型={target_model}"
                logger.warning("[vector-router] embedding 返回空向量")
                ctx.router_latency_ms = int((time.time() - start) * 1000)
                return

            # 3. 读取启用且有能力向量的模型
            models = await self._load_active_models()
            if not models:
                target_model = ctx.default_model or self.config.fallback_model
                ctx.target_model = target_model
                ctx.router_decision = f"vector: 无可用模型，使用默认模型={target_model}"
                ctx.router_latency_ms = int((time.time() - start) * 1000)
                return

            # 4. 计算相似度，选最高
            best_model, best_score = self._find_best_model(user_vector, models)

            # 5. 滞回阈值判定（当前模型从 ctx 读取）
            current_model = getattr(ctx, "current_model", None)
            if not current_model and ctx.default_model:
                current_model = ctx.default_model

            target_model = self._hysteresis_decision(
                best_model, best_score, current_model, models
            )

            # 6. 低置信度判定：如果最终模型相似度 < threshold_high，标记为低置信度
            #    上层（Executor）会根据此标记决定是否升级到 LLM 路由
            target_vec = next(
                (m.embedding_vector for m in models if m.model_name == target_model), None
            )
            target_score = cosine_similarity(user_vector, target_vec) if target_vec else 0

            ctx.target_model = target_model
            ctx.router_decision = (
                f"vector: 模型={target_model}(相似度={target_score:.3f})"
            )
            # 存储置信度供上层判断
            ctx.router_confidence = target_score
            logger.info(f"[vector-router] 路由决策: 模型={target_model}, 相似度={target_score:.3f}")

        except Exception as e:
            logger.error(f"[vector-router] 路由异常: {e}", exc_info=True)
            target_model = getattr(ctx, "default_model", None) or self.config.fallback_model
            ctx.target_model = target_model
            ctx.router_decision = f"vector: 路由异常({e})，使用默认模型={target_model}"
        finally:
            ctx.router_latency_ms = int((time.time() - start) * 1000)

    def _extract_latest_user_message(self, messages: List[dict]) -> str:
        """从消息列表中提取最新的 user 消息文本"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    return " ".join(texts).strip()
        return ""

    async def _load_active_models(self) -> List[ModelCatalog]:
        """加载所有启用且有能力向量的模型"""
        stmt = select(ModelCatalog).where(
            ModelCatalog.is_active == True,  # noqa: E712
            ModelCatalog.embedding_vector.isnot(None),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def _find_best_model(
        self, user_vector: List[float], models: List[ModelCatalog]
    ) -> Tuple[Optional[str], float]:
        """找相似度最高的模型"""
        best_model = None
        best_score = 0.0
        for m in models:
            if not m.embedding_vector:
                continue
            score = cosine_similarity(user_vector, m.embedding_vector)
            if score > best_score:
                best_score = score
                best_model = m.model_name
        return best_model, best_score

    def _hysteresis_decision(
        self,
        best_model: Optional[str],
        best_score: float,
        current_model: Optional[str],
        models: List[ModelCatalog],
    ) -> str:
        """
        滞回阈值决策（模型级滞回）：
        - 无当前模型 → 直接返回 best_model（首次请求不做滞回）
        - 有当前模型且当前模型相似度 >= threshold_low 且 best_score < threshold_high → 保持当前模型
        - best_score >= threshold_high → 切换到最优模型
        - 否则 → 保持当前模型（或 fallback）
        """
        threshold_high = self.config.threshold_high
        threshold_low = self.config.threshold_low

        if best_model is None:
            return current_model or self.config.fallback_model

        # 无当前模型（首次请求），直接返回最优模型
        if not current_model:
            return best_model

        # 有当前模型，检查滞回
        current_vec = next(
            (m.embedding_vector for m in models if m.model_name == current_model), None
        )
        if current_vec:
            current_score = cosine_similarity(
                self._last_user_vector or [], current_vec
            ) if hasattr(self, '_last_user_vector') else 0
            # 当前模型相似度还够高，且没有更优模型超过切入阈值，保持（防抖动）
            if current_score >= threshold_low and best_score < threshold_high:
                return current_model

        # 最高相似度超过切入阈值，切换
        if best_score >= threshold_high:
            return best_model

        # 都不满足，保持当前或 fallback
        return current_model or self.config.fallback_model
