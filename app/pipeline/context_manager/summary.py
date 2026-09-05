"""
摘要压缩策略（summary）—— 企业版

当对话超过阈值时，用摘要模型将历史压缩为一段摘要，
保留最近几轮 + 系统摘要，减少 token 消耗。
M1 阶段仅搭建框架，实际摘要调用在 M2 完善。

TODO(M2):
- 接入摘要模型（指定账号或本地 Ollama）
- 实现异步摘要预计算
- 维护 SessionState.summary
- 触发条件：summary_trigger_tokens / summary_trigger_turns
"""
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from app.pipeline.context_manager.base import ContextManager

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext, SessionState
    from app.pipeline.config import ContextConfig

logger = logging.getLogger(__name__)


class SummaryManager(ContextManager):
    """摘要压缩：历史摘要 + 最近轮次（M1 框架，M2 完善）"""

    name = "summary"

    def __init__(self, config: "ContextConfig"):
        self.config = config

    async def assemble(
        self,
        ctx: "PipelineContext",
        session: Optional["SessionState"] = None,
    ) -> List[Dict[str, Any]]:
        ctx.context_strategy = self.name

        # M1: 暂用直传，M2 实现摘要压缩
        ctx.assembled_messages = list(ctx.original_messages)
        ctx.summary_used = False
        logger.warning("[summary] M1 阶段暂未实现摘要压缩，回退直传")
        return ctx.assembled_messages

    async def update_summary(
        self,
        session: "SessionState",
        messages: List[Dict[str, Any]],
        response: str,
    ) -> None:
        # M1: 空实现，M2 接入摘要模型
        logger.debug("[summary] M1 阶段 update_summary 空实现")
