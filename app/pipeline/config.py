"""
管线配置——从 SystemConfig 反序列化，带缓存。

RouterConfig: ModelRouter 的完整配置（rules/vector/llm 三种策略的参数）
ContextConfig: ContextManager 的配置
PinSelectorConfig: AccountSelector pin 策略的配置
PipelineConfig: 汇总配置，从数据库加载并缓存 60 秒
"""
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import SystemConfig

logger = logging.getLogger(__name__)

# 配置缓存
_cache: Optional["PipelineConfig"] = None
_cache_time: float = 0.0
_CACHE_TTL = 60  # 秒


@dataclass
class RouterConfig:
    """ModelRouter 路由配置"""

    strategy: str = "off"  # off / rules / vector / llm
    fallback_domain: str = "general"

    # ── rules 策略 ──
    rules_match_mode: str = "any"  # any=命中任一 / all=全部命中

    # ── vector 策略：Embedding 后端 ──
    embedding_backend: str = "cloud"  # cloud / local

    # cloud 配置
    embedding_cloud_provider: str = "aliyun"  # aliyun / openai / custom
    embedding_cloud_base_url: str = ""
    embedding_cloud_api_key: str = ""  # 加密存储
    embedding_cloud_model: str = "text-embedding-v3"
    embedding_cloud_input_field: str = "input"
    embedding_cloud_output_path: str = "output.embeddings[0].embedding"
    embedding_cloud_dimensions: int = 1024

    # local 配置（选装插件，未安装不自动下载）
    embedding_local_plugin: str = "bge-small-zh"
    embedding_local_model_path: str = ""
    embedding_local_installed: bool = False

    # 领域原型与阈值
    domain_prototypes: Dict[str, str] = field(default_factory=dict)
    domain_prototype_vectors: Dict[str, List[float]] = field(default_factory=dict)
    threshold_high: float = 0.75  # 切入新领域阈值
    threshold_low: float = 0.60   # 切走当前领域阈值（滞回）

    # ── llm 策略：分类模型 ──
    classifier_deploy: str = "cloud"  # cloud / local
    classifier_account_id: int = 0
    classifier_local_model: str = ""
    classifier_prompt: str = (
        "你是一个对话分类器。请将以下用户请求分类到以下领域之一：{domains}。"
        "只输出领域名称，不要解释。\n\n用户请求：{text}"
    )
    classifier_max_tokens: int = 50


@dataclass
class ContextConfig:
    """ContextManager 上下文管理配置"""

    strategy: str = "passthrough"  # passthrough / window / summary
    window_turns: int = 10
    summary_model_account_id: int = 0  # 0=用当前账号
    summary_trigger_tokens: int = 4000
    summary_trigger_turns: int = 5


@dataclass
class PinSelectorConfig:
    """AccountSelector pin（指定模型）策略配置"""

    pin_model: str = ""          # 全局默认指定的真实模型名，空=不全局指定
    pin_account_id: int = 0      # 全局默认指定的账号 ID，0=不指定
    allow_override: bool = True  # 允许请求级 header 覆盖


@dataclass
class PipelineConfig:
    """
    管线汇总配置——从 SystemConfig 反序列化。

    默认值全部对齐现有行为：
    - router=off（不路由）
    - selector=pin（指定模型，等价现有 sequential 行为）
    - context=passthrough（直传）
    - edition=opensource
    """

    router_strategy: str
    router_config: RouterConfig
    selector_strategy: str
    pin_config: PinSelectorConfig
    context_strategy: str
    context_config: ContextConfig
    edition: str

    @classmethod
    async def load(cls, session: AsyncSession, force: bool = False) -> "PipelineConfig":
        """
        从数据库加载配置，缓存 60 秒。

        Args:
            session: 数据库会话
            force: 强制刷新缓存（管理界面修改配置后调用）
        """
        global _cache, _cache_time

        now = time.time()
        if not force and _cache is not None and (now - _cache_time) < _CACHE_TTL:
            return _cache

        result = await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
        config = result.scalar_one_or_none()

        if not config:
            config = SystemConfig(id=1)
            session.add(config)
            await session.commit()

        # 反序列化 JSON 配置字段（None 时用空 dict）
        router_json = _safe_json_load(getattr(config, "router_config_json", None))
        selector_json = _safe_json_load(getattr(config, "selector_config_json", None))
        context_json = _safe_json_load(getattr(config, "context_config_json", None))

        pipeline = cls(
            router_strategy=getattr(config, "router_strategy", "off") or "off",
            router_config=RouterConfig(**{**RouterConfig().__dict__, **router_json}),
            selector_strategy=getattr(config, "selector_strategy", "pin") or "pin",
            pin_config=PinSelectorConfig(**{**PinSelectorConfig().__dict__, **selector_json}),
            context_strategy=getattr(config, "context_strategy", "passthrough") or "passthrough",
            context_config=ContextConfig(**{**ContextConfig().__dict__, **context_json}),
            edition=getattr(config, "edition", "opensource") or "opensource",
        )

        _cache = pipeline
        _cache_time = now
        return pipeline

    @classmethod
    def invalidate_cache(cls) -> None:
        """使缓存失效（管理界面修改配置后调用）"""
        global _cache, _cache_time
        _cache = None
        _cache_time = 0.0
        logger.info("PipelineConfig 缓存已失效")


def _safe_json_load(value: Any) -> Dict[str, Any]:
    """安全解析 JSON，失败返回空 dict"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
