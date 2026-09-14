"""
安全审核插口（A8 契约）——v0.6.0 组件化/插件化预留

开源版默认 NoopSecurityGuard（零成本、零拦截）；
企业版可注册私有实现：敏感信息脱敏、Prompt Injection 防护、部门级内容策略。
详见 docs/extensions/02-hooks-spi.md 第 5 节。
"""
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.extensions.sdk import register_spi

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

SPI_SECURITY = "security"


class SecurityBlocked(Exception):
    """安全审核拦截：入站/出站内容违规时抛出"""

    def __init__(self, reason: str = "blocked by security guard", status_code: int = 403):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


class SecurityGuard(ABC):
    """安全审核守卫 SPI：入站内容过滤 + 出站内容审计"""

    name: str = "base"

    @abstractmethod
    async def check_input(self, ctx: "PipelineContext") -> None:
        """
        入站审核：在 classify 之前执行。
        违规/敏感内容 → raise SecurityBlocked 拒绝请求；
        可脱敏 → 改写 ctx.original_messages（谨慎，需与上下文工位协同）。
        """

    @abstractmethod
    async def check_output(self, ctx: "PipelineContext", response: dict) -> None:
        """
        出站审计：在执行工位拿到上游响应后执行。
        响应内容违规 → raise SecurityBlocked（调用方转 4xx/502）；
        可脱敏 → 原地改写 response。
        """


class NoopSecurityGuard(SecurityGuard):
    """默认安全守卫：放行一切（开源版行为，零成本）"""

    name = "noop"

    async def check_input(self, ctx: "PipelineContext") -> None:
        return None

    async def check_output(self, ctx: "PipelineContext", response: dict) -> None:
        return None


# 注册内置默认实现
register_spi(SPI_SECURITY, "noop", NoopSecurityGuard())


def get_security_guard() -> SecurityGuard:
    """取当前生效的安全守卫（默认 noop；企业版可注册覆盖）"""
    from app.extensions.sdk import spi_registry

    impls = spi_registry.list(SPI_SECURITY)
    # 取最后注册的实现（后注册优先）
    return next(reversed(list(impls.values()))) if impls else NoopSecurityGuard()
