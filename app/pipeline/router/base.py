"""
模型路由策略接口（选羊层）

根据消息语义决定领域标签和目标模型。
M1 阶段默认 off（不路由），行为与现有完全一致。
"""
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext


class ModelRouter(ABC):
    """模型路由策略抽象基类"""

    name: str = "base"

    @abstractmethod
    async def route(self, ctx: "PipelineContext") -> None:
        """
        执行路由决策，结果写入 ctx.domain_tag / ctx.target_model。

        Args:
            ctx: 管线上下文，读取 ctx.original_messages，写入 ctx.domain_tag/target_model
        """
        ...

    async def detect_drift(self, ctx: "PipelineContext", current_domain: Optional[str]) -> bool:
        """
        检测话题漂移（会话中使用，仅 vector/llm 策略有意义）。

        默认返回 False（不漂移），off/rules 策略不需要漂移检测。
        """
        return False
