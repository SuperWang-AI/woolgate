"""
分类引擎 SPI（A4 组件化 + A5 降级）——v0.6.0

把"智能分类"（判断用户请求该走哪个模型）抽为可替换组件：
- VectorClassifier：现有向量路由（embedding 相似度 + 滞回）
- LLMClassifier：现有 LLM 路由（小模型推荐 + 理由）
- LocalClassifier：本地模型分类（Ollama，预留；企业本地部署场景）
- ClassifierFactory：按配置创建（auto 推断 / 显式指定）

内置实现直接复用 v0.5.0 的 VectorRouter/LLMRouter（行为零变化），
组件化价值在于：新引擎只需实现 Classifier SPI，无需改 Executor。
详见 docs/extensions/04-classifier-engine.md。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Tuple, TYPE_CHECKING

from app.extensions.sdk import register_spi

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext
    from app.pipeline.config import RouterConfig
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SPI_CLASSIFIER = "classifier"


@dataclass
class ClassificationResult:
    """分类结果（契约 04 第 2 节）"""

    model: str = ""  # 推荐的目标模型名
    confidence: float = 0.0  # 置信度 0~1
    engine: str = ""  # 实际使用的引擎名
    decision: str = ""  # 人类可读决策说明
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)  # 引擎自定义附加信息


class Classifier(ABC):
    """分类引擎 SPI"""

    name: str = "base"

    @abstractmethod
    async def classify(self, ctx: "PipelineContext") -> ClassificationResult:
        """
        执行分类：读取 ctx.original_messages / ctx.current_model / ctx.default_model，
        返回 ClassificationResult，并同步写入 ctx.target_model / ctx.router_* 字段
        （保持与 v0.5.0 路由行为一致的副作用）。
        """
        ...


class VectorClassifier(Classifier):
    """向量分类：包装现有 VectorRouter（行为零变化）"""

    name = "vector"

    def __init__(self, config: "RouterConfig", db: Optional["AsyncSession"] = None):
        from app.pipeline.router.vector import VectorRouter

        self.config = config
        self.db = db
        self._router = VectorRouter(config, db=db)

    async def classify(self, ctx: "PipelineContext") -> ClassificationResult:
        await self._router.route(ctx)
        return ClassificationResult(
            model=ctx.target_model or "",
            confidence=ctx.router_confidence,
            engine=self.name,
            decision=ctx.router_decision,
            latency_ms=ctx.router_latency_ms,
        )


class LLMClassifier(Classifier):
    """LLM 分类：包装现有 LLMRouter（行为零变化）"""

    name = "llm"

    def __init__(self, config: "RouterConfig", db: Optional["AsyncSession"] = None):
        from app.pipeline.router.llm import LLMRouter

        self.config = config
        self.db = db
        self._router = LLMRouter(config, db=db)

    async def classify(self, ctx: "PipelineContext") -> ClassificationResult:
        await self._router.route(ctx)
        return ClassificationResult(
            model=ctx.target_model or "",
            confidence=ctx.router_confidence,
            engine=self.name,
            decision=ctx.router_decision,
            latency_ms=ctx.router_latency_ms,
        )


class LocalClassifier(Classifier):
    """
    本地模型分类（Ollama，预留）。

    v0.6.0 仅占位：企业本地部署场景用本地小模型做意图分类，
    实现随企业组件池提供（契约 04 第 2 节）。开源版显式选择时给出明确报错。
    """

    name = "local"

    def __init__(self, config: "RouterConfig", db: Optional["AsyncSession"] = None):
        self.config = config
        self.db = db

    async def classify(self, ctx: "PipelineContext") -> ClassificationResult:
        raise NotImplementedError(
            "本地分类引擎（local）尚未随开源版提供；请使用 vector/llm/hybrid 或注册自定义分类器"
        )


def _build_builtin_classifier(engine: str, config, db):
    """构造内置分类器实例"""
    if engine == "vector":
        return VectorClassifier(config, db=db)
    if engine == "llm":
        return LLMClassifier(config, db=db)
    if engine == "local":
        return LocalClassifier(config, db=db)
    return None


class ClassifierFactory:
    """分类器工厂：按 router_strategy + classifier_engine 创建 (主分类器, 升级分类器)"""

    @staticmethod
    def create(
        router_strategy: str,
        classifier_engine: str,
        config: "RouterConfig",
        db: Optional["AsyncSession"] = None,
    ) -> Tuple[Optional[Classifier], Optional[Classifier]]:
        """
        Returns:
            (primary, upgrade):
            - primary: 主分类器（None 表示不分类，等同 off）
            - upgrade: hybrid 时低置信度升级用的次分类器（否则 None）
        """
        # 显式指定引擎优先（auto 时按 router_strategy 推断）
        engine = classifier_engine if classifier_engine and classifier_engine != "auto" else router_strategy

        if engine == "hybrid":
            primary = _build_builtin_classifier("vector", config, db)
            upgrade = _build_builtin_classifier("llm", config, db)
            return primary, upgrade

        if engine in ("vector", "llm", "local"):
            primary = _build_builtin_classifier(engine, config, db)
            # 自定义注册的分类器覆盖内置（后注册优先）
            custom = _get_custom_classifier(engine)
            if custom:
                primary = custom
            return primary, None

        # off 或其他未知策略：不分类
        return None, None


def _get_custom_classifier(name: str) -> Optional[Classifier]:
    """查自定义注册的分类器（register_spi('classifier', name, impl)）"""
    from app.extensions.sdk import spi_registry

    return spi_registry.get(SPI_CLASSIFIER, name)


# 注册内置实现（供 register_spi 覆盖与文档一致性）
def _register_builtins() -> None:
    """内置分类器注册占位（实际由 ClassifierFactory 直接构造，注册仅为 SPI 目录可见）"""
    # 空实现：内置分类器走工厂直接构造，避免提前绑定 db
    pass


_register_builtins()
