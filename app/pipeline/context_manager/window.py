"""
滑动窗口策略（window）

只保留最近 N 轮对话（每轮 = user + assistant），丢弃更早的消息。
不做摘要，简单截断，零额外 token 消耗。
"""
import logging
import time
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from app.pipeline.context_manager.base import ContextManager

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext, SessionState

logger = logging.getLogger(__name__)


class WindowManager(ContextManager):
    """滑动窗口：只保留最近 N 轮对话"""

    name = "window"

    def __init__(self, window_turns: int = 10):
        self.window_turns = window_turns

    async def assemble(
        self,
        ctx: "PipelineContext",
        session: Optional["SessionState"] = None,
    ) -> List[Dict[str, Any]]:
        start = time.time()
        ctx.context_strategy = self.name
        messages = ctx.original_messages

        # 跨语义切换时 window 策略无法压缩上下文，记录 warning
        if getattr(ctx, "domain_switched", False):
            logger.warning(
                "[window] 检测到跨语义切换，但 window 策略不做摘要。"
                "建议改用 summary 策略以获得更好的切换效果。"
            )

        # 按轮次截断（每轮 = user + assistant）
        turn_count = self._count_turns(messages)
        if turn_count > self.window_turns:
            messages = self._take_recent_turns(messages, self.window_turns)
            logger.info(
                f"[window] 截断到最近 {self.window_turns} 轮（原 {turn_count} 轮，"
                f"{len(ctx.original_messages)} 条 → {len(messages)} 条）"
            )

        ctx.assembled_messages = list(messages)
        ctx.summary_used = False
        ctx.context_latency_ms = int((time.time() - start) * 1000)
        return ctx.assembled_messages

    def _count_turns(self, messages: List[Dict[str, Any]]) -> int:
        """统计对话轮次（user 消息数）"""
        return sum(1 for m in messages if m.get("role") == "user")

    def _take_recent_turns(self, messages: List[Dict[str, Any]], turns: int) -> List[Dict[str, Any]]:
        """取最近 N 轮对话（每轮 = user + assistant）"""
        if turns <= 0:
            return []
        user_count = 0
        cut_index = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                user_count += 1
                if user_count == turns:
                    cut_index = i
                    break
        return messages[cut_index:]
