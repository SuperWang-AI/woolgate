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

        # 按优先级降序排序（与现有 _select_sequential 完全一致）
        sorted_accounts = sorted(available_accounts, key=lambda x: x.priority, reverse=True)
        selected = sorted_accounts[0]
        logger.info(f"[free-first] 选中账号: {selected.id} (优先级: {selected.priority})")
        return selected
