"""
滑动窗口策略（window）—— 开源/企业版均可用

只保留最近 N 轮对话，丢弃更早的消息。
M1 阶段搭建框架，默认 window_turns=10。
"""
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from app.pipeline.context_manager.base import ContextManager

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext, SessionState

logger = logging.getLogger(__name__)


class WindowManager(ContextManager):
    """滑动窗口：只保留最近 N 条消息"""

    name = "window"

    def __init__(self, window_turns: int = 10):
        self.window_turns = window_turns

    async def assemble(
        self,
        ctx: "PipelineContext",
        session: Optional["SessionState"] = None,
    ) -> List[Dict[str, Any]]:
        ctx.context_strategy = self.name
        messages = ctx.original_messages

        # 保留最近 window_turns 条消息（每条消息算一个，不是一轮）
        if len(messages) > self.window_turns:
            messages = messages[-self.window_turns:]
            logger.info("[window] 截断到最近 %d 条消息（原 %d 条）",
                        self.window_turns, len(ctx.original_messages))

        ctx.assembled_messages = list(messages)
        return ctx.assembled_messages
