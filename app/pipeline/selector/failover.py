"""
主备模式策略（failover）—— 企业版

按 priority 降序，主账号优先，主不可用时自动切备。
由于 available_accounts 已经过滤了不可用账号，直接选优先级最高的即可。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class FailoverSelector(AccountSelector):
    """主备模式：按优先级选第一个（主不可用时已被过滤，自动切备）"""

    name = "failover"

    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        selected = self._pick_highest_priority(available_accounts)
        logger.info(f"[failover] 选中账号: {selected.id} (优先级: {selected.priority})")
        return selected
