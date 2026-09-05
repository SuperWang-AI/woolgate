"""
向量路由策略（vector）

通过 embedding 余弦相似度 + 领域原型向量 + 滞回阈值决定领域标签。
M2 实现完整路由逻辑：云端 embedding + 领域原型表 + 领域→模型映射。

滞回说明：
- threshold_high (默认 0.75)：最高相似度超过此值才切换到新领域
- threshold_low (默认 0.60)：当前领域相似度低于此值才允许切走
- 当前领域从 SessionState 读取（M2 第4步启用），本步先用 None（无滞回，每次选最高）
"""
import logging
import time
from typing import TYPE_CHECKING, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.router.base import ModelRouter
from app.services.embedding import EmbeddingService, cosine_similarity
from app.services.domain_service import DomainService
from app.models.database import DomainPrototype

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext
    from app.pipeline.config import RouterConfig

logger = logging.getLogger(__name__)


class VectorRouter(ModelRouter):
    """向量路由：embedding 相似度匹配领域原型"""

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
            ctx.domain_tag = self.config.fallback_domain
            ctx.router_decision = "vector: 无数据库会话，使用 fallback"
            logger.warning("[vector-router] 无 db 会话，回退 fallback_domain")
            return

        try:
            # 1. 提取最新用户消息
            user_text = self._extract_latest_user_message(ctx.original_messages)
            if not user_text:
                ctx.domain_tag = self.config.fallback_domain
                ctx.router_decision = "vector: 无用户消息，使用 fallback"
                return

            # 2. 计算用户消息向量
            embed_svc = self._get_embedding_service()
            user_vector = await embed_svc.embed(user_text)
            self._last_user_vector = user_vector
            if not user_vector:
                ctx.domain_tag = self.config.fallback_domain
                ctx.router_decision = "vector: embedding 失败，使用 fallback"
                logger.warning("[vector-router] embedding 返回空向量")
                return

            # 3. 读取启用的领域原型
            domains = await self._load_active_domains()
            if not domains:
                ctx.domain_tag = self.config.fallback_domain
                ctx.router_decision = "vector: 无启用领域，使用 fallback"
                return

            # 4. 计算相似度，选最高
            best_domain, best_score = self._find_best_domain(user_vector, domains)

            # 5. 滞回阈值判定（当前领域从 ctx 读取，M2-4 后从 SessionState 读）
            current_domain = getattr(ctx, "current_domain", None)
            target_domain = self._hysteresis_decision(
                best_domain, best_score, current_domain, domains
            )

            # 6. 从领域→模型映射选目标模型（按优先级，支持降级）
            target_model = await self._select_model_for_domain(target_domain)

            ctx.domain_tag = target_domain
            ctx.target_model = target_model
            ctx.router_decision = (
                f"vector: 领域={target_domain}(相似度={best_score:.3f}), "
                f"模型={target_model or '无映射'}"
            )
            logger.info(f"[vector-router] 路由决策: 领域={target_domain}, 相似度={best_score:.3f}, 模型={target_model}")

        except Exception as e:
            # 路由失败不阻塞请求，回退 fallback
            logger.error(f"[vector-router] 路由异常: {e}", exc_info=True)
            ctx.domain_tag = self.config.fallback_domain
            ctx.router_decision = f"vector: 路由异常({e})，使用 fallback"
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
                    # 多模态消息，提取文本部分
                    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    return " ".join(texts).strip()
        return ""

    async def _load_active_domains(self) -> List[DomainPrototype]:
        """加载所有启用且有向量的领域原型"""
        result = await self.db.execute(
            select(DomainPrototype).where(
                DomainPrototype.is_active == True,  # noqa: E712
                DomainPrototype.embedding_vector.isnot(None),
            )
        )
        return list(result.scalars().all())

    def _find_best_domain(
        self, user_vector: List[float], domains: List[DomainPrototype]
    ) -> Tuple[Optional[str], float]:
        """找相似度最高的领域"""
        best_domain = None
        best_score = 0.0
        for d in domains:
            if not d.embedding_vector:
                continue
            score = cosine_similarity(user_vector, d.embedding_vector)
            if score > best_score:
                best_score = score
                best_domain = d.name
        return best_domain, best_score

    def _hysteresis_decision(
        self,
        best_domain: Optional[str],
        best_score: float,
        current_domain: Optional[str],
        domains: List[DomainPrototype],
    ) -> str:
        """
        滞回阈值决策：
        - 有当前领域且当前领域相似度 > threshold_low → 保持当前领域（防抖动）
        - 最高相似度 > threshold_high → 切换到最高领域
        - 否则 → 保持当前领域（或 fallback）
        """
        threshold_high = self.config.threshold_high
        threshold_low = self.config.threshold_low

        # 没有候选领域，用 fallback
        if best_domain is None:
            return current_domain or self.config.fallback_domain

        # 有当前领域，检查是否还在安全区内
        if current_domain:
            current_vec = next(
                (d.embedding_vector for d in domains if d.name == current_domain), None
            )
            if current_vec:
                current_score = cosine_similarity(
                    self._last_user_vector or [], current_vec
                ) if hasattr(self, '_last_user_vector') else 0
                # 当前领域相似度还够高，且没有更优领域超过切入阈值，保持（防抖动）
                if current_score >= threshold_low and best_score < threshold_high:
                    return current_domain

        # 最高相似度超过切入阈值，切换
        if best_score >= threshold_high:
            return best_domain

        # 都不满足，保持当前或 fallback
        return current_domain or self.config.fallback_domain

    async def _select_model_for_domain(self, domain_name: str) -> Optional[str]:
        """从领域→模型映射中选优先级最高的启用模型，无则返回 None"""
        domain_svc = DomainService(self.db)
        models = await domain_svc.list_active_models_for_domain(domain_name)
        if models:
            return models[0]  # 已按优先级降序排列
        # 该领域无模型映射，尝试 fallback_domain 的模型
        if domain_name != self.config.fallback_domain:
            fallback_models = await domain_svc.list_active_models_for_domain(
                self.config.fallback_domain
            )
            if fallback_models:
                return fallback_models[0]
        return None
