"""
LLM 分类路由策略（llm）—— 企业版

用便宜小模型对用户请求进行分类，输出领域标签。
M1 阶段仅搭建框架，实际分类调用在 M2 完善。

TODO(M2):
- 接入分类模型（云端指定账号或本地 Ollama）
- 解析分类 prompt 输出
- 处理分类失败的降级逻辑
"""
import logging
from typing import TYPE_CHECKING

from app.pipeline.router.base import ModelRouter

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext
    from app.pipeline.config import RouterConfig

logger = logging.getLogger(__name__)


class LLMRouter(ModelRouter):
    """LLM 分类路由：小模型分类输出领域标签（M1 框架，M2 完善）"""

    name = "llm"

    def __init__(self, config: "RouterConfig"):
        self.config = config

    async def route(self, ctx: "PipelineContext") -> None:
        ctx.router_strategy = self.name
        # M1: 暂用 fallback_domain，M2 接入真实分类模型
        ctx.domain_tag = self.config.fallback_domain
        ctx.router_decision = f"llm: M1暂用fallback={self.config.fallback_domain}"
        logger.warning("[llm-router] M1 阶段暂未实现分类模型，使用 fallback_domain")
