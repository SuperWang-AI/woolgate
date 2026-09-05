"""
领域服务——DomainPrototype 和 DomainModelMapping 的 CRUD + 自动向量计算。

向量路由依赖领域原型的预计算向量，每个领域有多条典型用户示例，
保存/更新时自动调用 EmbeddingService 逐条计算并取平均。
"""
import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import DomainPrototype, DomainModelMapping
from app.services.embedding import EmbeddingService
from app.pipeline.config import RouterConfig

logger = logging.getLogger(__name__)


# 预置领域（每个领域10条口语化典型用户示例）
DEFAULT_DOMAINS = [
    {
        "name": "general",
        "description": "通用对话、日常聊天、问答、闲聊、生活建议、常识解答",
        "examples": [
            "你好",
            "今天天气怎么样",
            "帮我翻译这句话成英文",
            "北京有什么好玩的地方",
            "怎么煮面条好吃",
            "推荐一本好看的书",
            "失眠怎么办",
            "1+1等于几",
            "介绍一下长城",
            "今天心情不好，聊聊天",
        ],
    },
    {
        "name": "code",
        "description": "编程开发、代码编写、调试、算法、技术架构、API 设计、代码审查",
        "examples": [
            "用Python写一个快速排序",
            "这个报错是什么意思",
            "帮我设计一个登录接口",
            "JavaScript闭包怎么理解",
            "Docker怎么部署项目",
            "MySQL索引失效的原因",
            "写一个爬虫抓取网页",
            "Git合并冲突怎么解决",
            "RESTful API怎么设计",
            "这段代码有性能问题吗",
        ],
    },
    {
        "name": "creative",
        "description": "文案写作、创意构思、故事创作、营销文案、诗歌、内容生成",
        "examples": [
            "写一首关于秋天的诗",
            "帮我想一个品牌名字",
            "写一段产品营销文案",
            "编一个科幻小故事",
            "给咖啡店写一句广告语",
            "帮我写一封情书",
            "想几个短视频脚本",
            "写一篇端午节公众号文章",
            "给孩子讲个睡前故事",
            "帮我改一下这段文案，更有感染力",
        ],
    },
    {
        "name": "data",
        "description": "数据分析、统计、报表、SQL、数据可视化、商业分析、数据建模",
        "examples": [
            "帮我分析上个月的销售数据",
            "写一个SQL查询用户留存",
            "这个报表怎么做",
            "AB测试结果怎么看",
            "用Excel做一个数据透视表",
            "转化率下降了，帮我分析原因",
            "画一个销售趋势图",
            "用户画像怎么构建",
            "同比环比怎么计算",
            "这批数据有什么异常",
        ],
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
        self, name: str,
        description: Optional[str] = None,
        examples: Optional[List[str]] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> DomainPrototype:
        """创建领域，自动计算向量（优先用 examples 平均，回退 description）"""
        domain = DomainPrototype(name=name, description=description, examples=examples)
        self.db.add(domain)
        await self.db.flush()

        if embedding_service:
            await self._compute_embedding(domain, embedding_service)

        await self.db.commit()
        await self.db.refresh(domain)
        logger.info(f"创建领域: {name} (id={domain.id}, examples={len(examples or [])})")
        return domain

    async def update_domain(
        self, domain_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        examples: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> Optional[DomainPrototype]:
        """更新领域，examples/description 变更时自动重算向量"""
        domain = await self.get_domain(domain_id)
        if not domain:
            return None

        if name is not None:
            domain.name = name
        if description is not None:
            domain.description = description
        if examples is not None:
            domain.examples = examples
        if is_active is not None:
            domain.is_active = is_active

        # examples 或 description 变更时重算向量
        if (examples is not None or description is not None) and embedding_service:
            await self._compute_embedding(domain, embedding_service)

        await self.db.commit()
        await self.db.refresh(domain)
        return domain

    async def delete_domain(self, domain_id: int) -> bool:
        """删除领域（同时删除关联的模型映射）"""
        domain = await self.get_domain(domain_id)
        if not domain:
            return False

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
        """计算并存储领域向量：优先用 examples 多条平均，回退 description 单条"""
        try:
            texts = domain.examples if domain.examples else [domain.description or domain.name]
            if not texts or not any(texts):
                logger.warning(f"领域 {domain.name} 无有效文本，跳过向量计算")
                return

            # 逐条计算 embedding，取平均
            vectors = []
            for text in texts:
                if not text or not text.strip():
                    continue
                vec = await embedding_service.embed(text)
                if vec:
                    vectors.append(vec)

            if not vectors:
                logger.warning(f"领域 {domain.name} 所有示例向量计算失败")
                return

            # 平均向量
            dim = len(vectors[0])
            avg_vector = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
            domain.embedding_vector = avg_vector
            logger.info(f"领域 {domain.name} 向量已更新（{len(vectors)}条示例平均，维度={dim}）")
        except Exception as e:
            logger.error(f"计算领域 {domain.name} 向量失败: {e}")

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
        """确保预置领域存在（首次启动时调用），使用多示例平均向量"""
        existing = await self.list_domains()
        existing_names = {d.name for d in existing}

        for preset in DEFAULT_DOMAINS:
            if preset["name"] not in existing_names:
                domain = await self.create_domain(
                    name=preset["name"],
                    description=preset["description"],
                    examples=preset["examples"],
                    embedding_service=embedding_service,
                )
                for model_name, priority in DEFAULT_DOMAIN_MODELS.get(preset["name"], []):
                    await self.add_mapping(domain.id, model_name, priority)
            else:
                # 已存在但没有 examples 的旧领域，补充示例（向量由后续 recompute_all_embeddings 统一计算）
                existing_domain = next((d for d in existing if d.name == preset["name"]), None)
                if existing_domain and not existing_domain.examples:
                    existing_domain.examples = preset["examples"]
                    await self.db.commit()
                    logger.info(f"领域 {existing_domain.name} 已补充 {len(preset['examples'])} 条示例")

        logger.info("预置领域初始化完成（多示例平均向量）")
