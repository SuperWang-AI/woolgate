"""
不路由策略（off）—— 默认策略

不做任何路由决策，domain_tag=None，所有账号平级。
行为与现有系统完全一致（M1 阶段默认使用此策略）。
"""
import logging
from typing import TYPE_CHECKING

from app.pipeline.router.base import ModelRouter

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


class OffRouter(ModelRouter):
    """不路由：直接透传，不修改 ctx"""

    name = "off"

    async def route(self, ctx: "PipelineContext") -> None:
        # 不做任何路由决策，保持 ctx.domain_tag=None, ctx.target_model=None
        ctx.router_strategy = self.name
        ctx.router_decision = "off: 不路由"
        logger.debug("[off-router] 不路由，透传")
