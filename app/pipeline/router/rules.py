"""
关键词路由策略（rules）—— 开源/企业版均可用

根据 RouterRule 表中的关键词/正则匹配，决定领域标签。
M1 阶段 RouterRule 表为空，实际行为与 off 一致（不影响现有功能）。

匹配逻辑：
1. 按 priority 降序遍历启用的规则
2. 有 pattern（正则）→ 优先正则匹配
3. 无 pattern → 关键词匹配（any=命中任一 / all=全部命中）
4. 命中第一条规则 → 设置 domain_tag，停止匹配
"""
import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.router.base import ModelRouter
from app.models.database import RouterRule

if TYPE_CHECKING:
    from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


class RulesRouter(ModelRouter):
    """关键词路由：按 RouterRule 表匹配领域标签"""

    name = "rules"

    def __init__(self, db: AsyncSession, match_mode: str = "any"):
        self.db = db
        self.match_mode = match_mode  # any / all

    async def route(self, ctx: "PipelineContext") -> None:
        ctx.router_strategy = self.name

        # 拼接所有用户消息文本
        text = " ".join(
            msg.get("content", "") for msg in ctx.original_messages
            if msg.get("role") == "user"
        )
        if not text:
            ctx.router_decision = "rules: 无用户消息"
            return

        # 按优先级降序查询启用的规则
        result = await self.db.execute(
            select(RouterRule)
            .where(RouterRule.is_active == True)
            .order_by(RouterRule.priority.desc())
        )
        rules = result.scalars().all()

        for rule in rules:
            if self._match_rule(rule, text):
                ctx.domain_tag = rule.domain_tag
                ctx.router_decision = f"rules: 命中规则 {rule.id} → {rule.domain_tag}"
                logger.info(f"[rules-router] 命中规则 {rule.id}: {rule.domain_tag}")
                return

        ctx.router_decision = "rules: 无匹配规则"
        logger.debug("[rules-router] 无匹配规则")

    def _match_rule(self, rule: RouterRule, text: str) -> bool:
        """匹配单条规则"""
        # 正则优先
        if rule.pattern:
            try:
                return re.search(rule.pattern, text, re.IGNORECASE) is not None
            except re.error:
                logger.warning(f"规则 {rule.id} 正则无效: {rule.pattern}")
                return False

        # 关键词匹配
        keywords = rule.keywords or []
        if not keywords:
            return False

        if self.match_mode == "all":
            return all(kw.lower() in text.lower() for kw in keywords)
        # any（默认）
        return any(kw.lower() in text.lower() for kw in keywords)
