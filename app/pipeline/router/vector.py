"""
向量路由策略（vector）—— 企业版

通过 embedding 余弦相似度 + 领域原型向量 + 滞回阈值决定领域标签。
M1 阶段仅搭建框架，实际 embedding 调用在 M2 完善。

TODO(M2):
- 接入云端 embedding（阿里百炼 text-embedding-v3）或本地插件
- 维护领域原型向量（domain_prototype_vectors）
- 实现滞回阈值逻辑（threshold_high / threshold_low）
"""
import logging
from typing import TYPE_CHECKING

from app.pipeline.router.base import ModelRouter

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext
    from app.pipeline.config import RouterConfig

logger = logging.getLogger(__name__)


class VectorRouter(ModelRouter):
    """向量路由：embedding 相似度匹配领域原型（M1 框架，M2 完善）"""

    name = "vector"

    def __init__(self, config: "RouterConfig"):
        self.config = config

    async def route(self, ctx: "PipelineContext") -> None:
        ctx.router_strategy = self.name
        # M1: 暂用 fallback_domain，M2 接入真实 embedding
        ctx.domain_tag = self.config.fallback_domain
        ctx.router_decision = f"vector: M1暂用fallback={self.config.fallback_domain}"
        logger.warning("[vector-router] M1 阶段暂未实现 embedding，使用 fallback_domain")
