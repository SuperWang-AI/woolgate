"""
模型能力清单服务——LLM 智能路由的核心配置管理

负责：
- 模型能力描述的 CRUD
- 能力描述的自动生成（预置模板 + LLM 生成草稿）
- 能力向量的自动计算（embedding）
- 预置主流模型的能力描述模板
"""
import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import ModelCatalog

logger = logging.getLogger(__name__)

# 预置主流模型的能力描述模板
PRESET_MODEL_DESCRIPTIONS = {
    "qwen-plus": {
        "vendor": "阿里百炼",
        "capability_description": "通义千问中等尺寸模型，具备较强的代码生成、数学推理和多语言能力，适合编程任务、技术问答、数据分析和复杂推理场景。",
        "capability_tags": ["code", "reasoning", "multilingual", "data"],
        "input_price": 0.8,
        "output_price": 2.0,
        "context_window": 131072,
    },
    "qwen-turbo": {
        "vendor": "阿里百炼",
        "capability_description": "通义千问轻量快速模型，响应速度快，适合简单问答、文本分类、摘要生成和路由决策等低延迟场景。",
        "capability_tags": ["fast", "chat", "classification", "routing"],
        "input_price": 0.3,
        "output_price": 0.6,
        "context_window": 131072,
    },
    "kimi-k2.6": {
        "vendor": "月之暗面",
        "capability_description": "Moonshot 推理模型，具备强创意写作、长文本理解和深度思考能力，适合文案创作、故事生成、文档分析和复杂推理。注意：推理模型 temperature 固定为 1。",
        "capability_tags": ["creative", "reasoning", "long-context", "writing"],
        "input_price": 4.0,
        "output_price": 21.0,
        "context_window": 262144,
    },
    "deepseek-chat": {
        "vendor": "DeepSeek",
        "capability_description": "DeepSeek 通用对话模型，代码能力突出，适合编程辅助、技术问答和通用对话场景。",
        "capability_tags": ["code", "chat", "reasoning"],
        "input_price": 1.0,
        "output_price": 2.0,
        "context_window": 65536,
    },
    "gpt-4o": {
        "vendor": "OpenAI",
        "capability_description": "GPT-4o 多模态模型，综合能力强，支持文本和图像输入，适合复杂推理、多模态理解和高质量生成。",
        "capability_tags": ["multimodal", "reasoning", "creative", "code"],
        "input_price": 5.0,
        "output_price": 15.0,
        "context_window": 128000,
    },
}


class ModelCatalogService:
    """模型能力清单服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_models(self) -> List[ModelCatalog]:
        """列出所有启用的模型（含能力向量）"""
        result = await self.db.execute(
            select(ModelCatalog).where(ModelCatalog.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_by_model_name(self, model_name: str) -> Optional[ModelCatalog]:
        """按模型名获取"""
        result = await self.db.execute(
            select(ModelCatalog).where(ModelCatalog.model_name == model_name)
        )
        return result.scalar_one_or_none()

    async def ensure_model(self, model_name: str, vendor: str = "") -> ModelCatalog:
        """
        确保模型存在于目录中，不存在则自动创建。

        优先级：
        1. 已存在 → 直接返回
        2. 匹配预置模板 → 用预置能力描述创建
        3. 未匹配 → 用通用描述创建（后续可由 LLM 生成更准确的描述）
        """
        existing = await self.get_by_model_name(model_name)
        if existing:
            return existing

        # 匹配预置模板
        preset = PRESET_MODEL_DESCRIPTIONS.get(model_name)
        if preset:
            model = ModelCatalog(
                vendor=preset["vendor"],
                model_name=model_name,
                display_name=model_name,
                capability_description=preset["capability_description"],
                capability_tags=preset["capability_tags"],
                input_price=preset["input_price"],
                output_price=preset["output_price"],
                context_window=preset["context_window"],
                is_active=True,
            )
        else:
            # 未匹配预置模板，用通用描述
            model = ModelCatalog(
                vendor=vendor or "unknown",
                model_name=model_name,
                display_name=model_name,
                capability_description=f"{vendor} {model_name} 模型，具备通用对话和生成能力。",
                capability_tags=["chat", "general"],
                is_active=True,
            )

        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        logger.info(f"模型目录新增: {model_name} (vendor={vendor})")
        return model

    async def update_capability_description(
        self, model_name: str, description: str
    ) -> Optional[ModelCatalog]:
        """更新能力描述"""
        model = await self.get_by_model_name(model_name)
        if not model:
            return None
        model.capability_description = description
        model.embedding_vector = None  # 清空旧向量，待重新计算
        await self.db.commit()
        await self.db.refresh(model)
        return model

    async def update_embedding_vector(
        self, model_name: str, vector: List[float]
    ) -> Optional[ModelCatalog]:
        """更新能力向量"""
        model = await self.get_by_model_name(model_name)
        if not model:
            return None
        model.embedding_vector = vector
        await self.db.commit()
        await self.db.refresh(model)
        return model

    async def recompute_all_embeddings(self, embedding_service) -> int:
        """
        重新计算所有启用模型的能力向量。

        Args:
            embedding_service: EmbeddingService 实例

        Returns:
            更新的模型数量
        """
        models = await self.list_active_models()
        count = 0
        for model in models:
            if not model.capability_description:
                continue
            try:
                vector = await embedding_service.embed(model.capability_description)
                if vector:
                    model.embedding_vector = vector
                    count += 1
            except Exception as e:
                logger.warning(f"模型 {model.model_name} 向量计算失败: {e}")
        await self.db.commit()
        logger.info(f"模型能力向量重算完成: {count}/{len(models)} 个模型")
        return count

    async def generate_description_with_llm(
        self, model_name: str, vendor: str, llm_client
    ) -> str:
        """
        用 LLM 生成模型能力描述草稿（用于未匹配预置模板的新模型）。

        Args:
            model_name: 模型名
            vendor: 厂商
            llm_client: LLM 客户端

        Returns:
            生成的能力描述
        """
        prompt = (
            f"请用一句话描述 {vendor} 的 {model_name} 模型的核心能力特点，"
            f"包括擅长的任务类型、适用场景、主要优势。"
            f"要求：50-100字，客观准确，适合用于 AI 路由决策。"
        )
        try:
            response = await llm_client.chat(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                max_tokens=200,
            )
            description = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if description:
                return description.strip()
        except Exception as e:
            logger.warning(f"LLM 生成能力描述失败 ({model_name}): {e}")

        # 降级：通用描述
        return f"{vendor} {model_name} 模型，具备通用对话和生成能力。"
