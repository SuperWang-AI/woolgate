"""
免费额度优先策略（对应现有 sequential）

按 priority 降序排序，选择第一个可用账号。
行为与现有 AccountRouter._select_sequential 完全一致。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class FreeFirstSelector(AccountSelector):
    """免费额度优先：按优先级降序选第一个"""

    name = "free-first"

    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        # 如果指定了目标模型，先过滤出匹配该模型的账号
        candidates = available_accounts
        if model_name:
            matched = [a for a in available_accounts if a.model_name == model_name]
            if matched:
                candidates = matched
                logger.info(f"[free-first] 按目标模型 {model_name} 过滤: {len(matched)}/{len(available_accounts)} 个账号匹配")
            else:
                logger.warning(f"[free-first] 无账号匹配模型 {model_name}，回退到全部可用账号")

        # 按优先级降序排序
        sorted_accounts = sorted(candidates, key=lambda x: x.priority, reverse=True)
        selected = sorted_accounts[0]
        logger.info(f"[free-first] 选中账号: {selected.id} (模型: {selected.model_name}, 优先级: {selected.priority})")
        return selected
