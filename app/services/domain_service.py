"""
领域服务——DomainPrototype 和 DomainModelMapping 的 CRUD + 自动向量计算。

向量路由依赖领域原型的预计算向量，每次保存/更新领域描述时自动调用 EmbeddingService 重算。
"""
import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import DomainPrototype, DomainModelMapping
from app.services.embedding import EmbeddingService
from app.pipeline.config import RouterConfig

logger = logging.getLogger(__name__)


# 预置领域（首次启动时自动插入）
DEFAULT_DOMAINS = [
    {
        "name": "general",
        "description": "通用对话、日常聊天、问答、闲聊、生活建议、常识解答",
    },
    {
        "name": "code",
        "description": "编程开发、代码编写、调试、算法、技术架构、API 设计、代码审查",
    },
    {
        "name": "creative",
        "description": "文案写作、创意构思、故事创作、营销文案、诗歌、内容生成",
    },
    {
        "name": "data",
        "description": "数据分析、统计、报表、SQL、数据可视化、商业分析、数据建模",
    },
]

# 预置领域→模型映射
DEFAULT_DOMAIN_MODELS = {
    "general": [("kimi-k2.6", 10)],
    "code": [("qwen-plus", 10)],
    "creative": [("kimi-k2.6", 10)],
    "data": [("qwen-plus", 10)],
}


class DomainService:
    """领域原型与模型映射服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 领域原型 CRUD ──

    async def list_domains(self, active_only: bool = False) -> List[DomainPrototype]:
        """列出所有领域"""
        stmt = select(DomainPrototype).order_by(DomainPrototype.id.asc())
        if active_only:
            stmt = stmt.where(DomainPrototype.is_active == True)  # noqa: E712
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_domain(self, domain_id: int) -> Optional[DomainPrototype]:
        """按 ID 获取领域"""
        result = await self.db.execute(
            select(DomainPrototype).where(DomainPrototype.id == domain_id)
        )
        return result.scalar_one_or_none()

    async def get_domain_by_name(self, name: str) -> Optional[DomainPrototype]:
        """按名称获取领域"""
        result = await self.db.execute(
            select(DomainPrototype).where(DomainPrototype.name == name)
        )
        return result.scalar_one_or_none()

    async def create_domain(
        self, name: str, description: str,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> DomainPrototype:
        """创建领域，自动计算向量"""
        domain = DomainPrototype(name=name, description=description)
        self.db.add(domain)
        await self.db.flush()  # 获取 id

        if embedding_service:
            await self._compute_embedding(domain, embedding_service)

        await self.db.commit()
        await self.db.refresh(domain)
        logger.info(f"创建领域: {name} (id={domain.id})")
        return domain

    async def update_domain(
        self, domain_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> Optional[DomainPrototype]:
        """更新领域，描述变更时自动重算向量"""
        domain = await self.get_domain(domain_id)
        if not domain:
            return None

        if name is not None:
            domain.name = name
        if description is not None:
            domain.description = description
            # 描述变更，重算向量
            if embedding_service:
                await self._compute_embedding(domain, embedding_service)
        if is_active is not None:
            domain.is_active = is_active

        await self.db.commit()
        await self.db.refresh(domain)
        return domain

    async def delete_domain(self, domain_id: int) -> bool:
        """删除领域（同时删除关联的模型映射）"""
        domain = await self.get_domain(domain_id)
        if not domain:
            return False

        # 删除关联的模型映射
        mappings = await self.list_mappings(domain_id)
        for m in mappings:
            await self.db.delete(m)

        await self.db.delete(domain)
        await self.db.commit()
        logger.info(f"删除领域: {domain.name} (id={domain_id})")
        return True

    async def recompute_all_embeddings(self, embedding_service: EmbeddingService) -> int:
        """重算所有领域的向量（配置变更后调用）"""
        domains = await self.list_domains()
        count = 0
        for domain in domains:
            try:
                await self._compute_embedding(domain, embedding_service)
                count += 1
            except Exception as e:
                logger.error(f"重算领域 {domain.name} 向量失败: {e}")
        await self.db.commit()
        return count

    async def _compute_embedding(self, domain: DomainPrototype, embedding_service: EmbeddingService):
        """计算并存储领域描述的向量"""
        try:
            vector = await embedding_service.embed(domain.description)
            domain.embedding_vector = vector
            logger.info(f"领域 {domain.name} 向量已更新（维度={len(vector)}）")
        except Exception as e:
            logger.error(f"计算领域 {domain.name} 向量失败: {e}")
            # 向量计算失败不阻塞保存，保留旧向量或 None

    # ── 领域→模型映射 CRUD ──

    async def list_mappings(self, domain_id: int) -> List[DomainModelMapping]:
        """列出某领域下的模型映射（按优先级降序）"""
        result = await self.db.execute(
            select(DomainModelMapping)
            .where(DomainModelMapping.domain_id == domain_id)
            .order_by(DomainModelMapping.priority.desc(), DomainModelMapping.id.asc())
        )
        return list(result.scalars().all())

    async def list_active_models_for_domain(self, domain_name: str) -> List[str]:
        """获取某领域下启用的模型名列表（按优先级降序），用于路由后选模型"""
        domain = await self.get_domain_by_name(domain_name)
        if not domain:
            return []
        result = await self.db.execute(
            select(DomainModelMapping)
            .where(
                DomainModelMapping.domain_id == domain.id,
                DomainModelMapping.is_active == True,  # noqa: E712
            )
            .order_by(DomainModelMapping.priority.desc(), DomainModelMapping.id.asc())
        )
        return [m.model_name for m in result.scalars().all()]

    async def add_mapping(
        self, domain_id: int, model_name: str, priority: int = 50,
    ) -> DomainModelMapping:
        """添加领域→模型映射"""
        mapping = DomainModelMapping(
            domain_id=domain_id, model_name=model_name, priority=priority,
        )
        self.db.add(mapping)
        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    async def update_mapping(
        self, mapping_id: int,
        model_name: Optional[str] = None,
        priority: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[DomainModelMapping]:
        """更新模型映射"""
        result = await self.db.execute(
            select(DomainModelMapping).where(DomainModelMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            return None
        if model_name is not None:
            mapping.model_name = model_name
        if priority is not None:
            mapping.priority = priority
        if is_active is not None:
            mapping.is_active = is_active
        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    async def delete_mapping(self, mapping_id: int) -> bool:
        """删除模型映射"""
        result = await self.db.execute(
            select(DomainModelMapping).where(DomainModelMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            return False
        await self.db.delete(mapping)
        await self.db.commit()
        return True

    # ── 初始化预置数据 ──

    async def ensure_default_domains(self, embedding_service: Optional[EmbeddingService] = None):
        """确保预置领域存在（首次启动时调用）"""
        existing = await self.list_domains()
        existing_names = {d.name for d in existing}

        for preset in DEFAULT_DOMAINS:
            if preset["name"] not in existing_names:
                domain = await self.create_domain(
                    name=preset["name"],
                    description=preset["description"],
                    embedding_service=embedding_service,
                )
                # 添加预置模型映射
                for model_name, priority in DEFAULT_DOMAIN_MODELS.get(preset["name"], []):
                    await self.add_mapping(domain.id, model_name, priority)

        logger.info("预置领域初始化完成")
