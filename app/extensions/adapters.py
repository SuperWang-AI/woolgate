"""
客户端适配器 SPI（A7 契约）——v0.6.0 组件化/插件化预留

只定义接口 + OpenAI 兼容默认实现（行为零变化）。
非 OpenAI 兼容客户端（MCP/自研协议等）后续以注册新 Adapter 的方式接入，
核心管线不动。详见 docs/extensions/05-client-adapters.md。
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING

from app.extensions.sdk import register_spi

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

SPI_ADAPTER = "adapter"


class ClientAdapter(ABC):
    """客户端协议适配器 SPI"""

    name: str = "base"

    def matches(self, request: Any) -> bool:
        """判断是否处理该请求（按路径/头部/内容类型识别）"""
        return False

    async def parse(self, request: Any, db: Any = None) -> Optional["PipelineContext"]:
        """把客户端请求解析为管线上下文（含 session_id/密钥/覆盖字段）"""
        raise NotImplementedError

    async def build_response(self, result: Any, ctx: "PipelineContext") -> Any:
        """把管线结果编码回客户端协议响应"""
        raise NotImplementedError


class OpenAICompatAdapter(ClientAdapter):
    """OpenAI 兼容协议默认实现（现有 /v1/chat/completions 行为）"""

    name = "openai-compat"

    def matches(self, request: Any) -> bool:
        # 默认兜底适配器：路径以 /v1/ 开头即视为 OpenAI 兼容
        path = getattr(request, "url", None)
        if path is not None:
            return str(path).startswith("/v1/")
        return True

    async def parse(self, request: Any, db: Any = None) -> Optional["PipelineContext"]:
        # v0.6.0：由 app/routes/api.py 现有 chat_completions 逻辑实现（行为不变）
        return None

    async def build_response(self, result: Any, ctx: "PipelineContext") -> Any:
        return result


register_spi(SPI_ADAPTER, "openai-compat", OpenAICompatAdapter())


def get_adapter(request: Any) -> ClientAdapter:
    """按请求分发适配器：匹配成功的第一人，默认 OpenAI 兼容（永不失败）"""
    from app.extensions.sdk import spi_registry

    impls = spi_registry.list(SPI_ADAPTER)
    # 按注册顺序匹配（内置 openai-compat 最后兜底）
    for impl in impls.values():
        try:
            if impl.matches(request):
                return impl
        except Exception as e:
            logger.warning(f"[adapters] 适配器 {impl.name} matches() 异常: {e}")
    return OpenAICompatAdapter()
