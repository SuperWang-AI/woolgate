"""
管线配置——从 SystemConfig 反序列化，带缓存。

RouterConfig: ModelRouter 的完整配置（vector/llm/hybrid 策略的参数）
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

    strategy: str = "hybrid"  # off / vector / llm / hybrid
    fallback_model: str = ""  # 兜底模型名，空=自动选第一个启用账号的模型

    # ── v0.6.0 分类引擎组件化（契约 04）──
    classifier_engine: str = "auto"  # auto/vector/llm/local/hybrid；auto=按 strategy 推断
    degrade_strategy: str = "fallback_model"  # 分类降级策略：fallback_model（默认）/ direct

    # ── vector 策略：Embedding 后端 ──
    embedding_backend: str = "cloud"  # cloud / local

    # cloud 配置
    embedding_cloud_provider: str = "aliyun"  # aliyun / openai / custom
    embedding_cloud_base_url: str = ""
    embedding_model_id: int = 0  # 使用哪个embedding模型（ModelCatalog的ID），0=自动选第一个
    embedding_cloud_model: str = "text-embedding-v3"  # 模型名（从ModelCatalog获取）
    embedding_cloud_input_field: str = "input"
    embedding_cloud_output_path: str = "output.embeddings[0].embedding"
    embedding_cloud_dimensions: int = 1024

    # local 配置（选装插件，未安装不自动下载）
    embedding_local_plugin: str = "bge-small-zh"
    embedding_local_model_path: str = ""
    embedding_local_installed: bool = False

    # 向量匹配阈值（M4 适配模型能力向量的相似度分布）
    threshold_high: float = 0.65  # 高置信度阈值，超过则向量路由直接用
    threshold_low: float = 0.55   # 滞回低阈值，当前模型相似度低于此值才允许切走

    # ── llm 策略：路由模型 ──
    router_model: str = ""  # 空=自动选最便宜最快的启用模型
    classifier_max_tokens: int = 200   # 路由分类模型输出上限
    classifier_temperature: float = 0.3  # 路由分类模型温度（低=更确定的分类）


@dataclass
class ContextConfig:
    """ContextManager 上下文管理配置"""

    strategy: str = "passthrough"  # passthrough / window / summary
    window_turns: int = 10

    # ── summary 策略：摘要模型配置 ──
    summary_provider: str = "cloud"  # cloud / local
    summary_model: str = ""  # cloud 时为模型名（从账号池选）；local 时为 Ollama 模型名
    summary_model_account_id: int = 0  # 0=自动选该模型的启用账号
    summary_trigger_tokens: int = 4000
    summary_trigger_turns: int = 20
    summary_window_turns: int = 5  # 摘要后保留最近 N 轮原文
    summary_max_tokens: int = 500   # 摘要模型输出上限


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

        # 兼容容错：过滤存量配置中的已废弃字段（M2-M3 遗留），避免未知字段报错
        router_json = _filter_known_fields(router_json, RouterConfig)
        selector_json = _filter_known_fields(selector_json, PinSelectorConfig)
        context_json = _filter_known_fields(context_json, ContextConfig)

        pipeline = cls(
            router_strategy=getattr(config, "router_strategy", "hybrid") or "hybrid",
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


def _filter_known_fields(data: Dict[str, Any], cfg_cls: Any) -> Dict[str, Any]:
    """过滤配置 dict 中的未知字段（dataclass 严格校验，废弃字段直接剔除）"""
    if not data:
        return data
    known = set(cfg_cls.__dataclass_fields__.keys())
    return {k: v for k, v in data.items() if k in known}
