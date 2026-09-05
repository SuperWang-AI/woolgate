"""
上下文管理策略接口

负责组装实际发给上游的 messages，支持直传、滑动窗口、摘要压缩三种策略。
M1 阶段默认 passthrough（直传），行为与现有完全一致。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext, SessionState


class ContextManager(ABC):
    """上下文管理策略抽象基类"""

    name: str = "base"

    @abstractmethod
    async def assemble(
        self,
        ctx: "PipelineContext",
        session: Optional["SessionState"] = None,
    ) -> List[Dict[str, Any]]:
        """
        组装实际发给上游的 messages。

        Args:
            ctx: 管线上下文，读取 ctx.original_messages
            session: 会话状态（summary 策略用，其他策略忽略）

        Returns:
            组装后的 messages 列表
        """
        ...

    async def update_summary(
        self,
        session: "SessionState",
        messages: List[Dict[str, Any]],
        response: str,
    ) -> None:
        """
        异步更新会话摘要（仅 summary 策略有实际实现）。
        默认空实现，其他策略不需要。
        """
        pass
