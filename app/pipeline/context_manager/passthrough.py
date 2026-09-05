"""
直传策略（passthrough）—— 默认策略

直接将原始消息透传给上游，不做任何修改。
行为与现有系统完全一致（M1 阶段默认使用此策略）。
"""
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from app.pipeline.context_manager.base import ContextManager

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext, SessionState

logger = logging.getLogger(__name__)


class PassthroughManager(ContextManager):
    """直传：原样返回原始消息"""

    name = "passthrough"

    async def assemble(
        self,
        ctx: "PipelineContext",
        session: Optional["SessionState"] = None,
    ) -> List[Dict[str, Any]]:
        ctx.context_strategy = self.name
        ctx.assembled_messages = list(ctx.original_messages)
        logger.debug("[passthrough] 直传 %d 条消息", len(ctx.original_messages))
        return ctx.assembled_messages
