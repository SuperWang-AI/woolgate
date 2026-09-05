"""
会话粘性策略（sticky）—— 企业版

优先使用上一次的账号，保持会话连续性。
如果上一次账号不可用，回退到 free-first。

注意：现有 AccountRouter 的粘性逻辑在 select_account 入口处统一处理（_infer_previous_account），
本策略是为第4步统一 Executor 后准备的独立实现。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class StickySelector(AccountSelector):
    """会话粘性：优先用上次账号，否则按优先级选第一个"""

    name = "sticky"

    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        # 优先使用上一次的账号
        if previous_account_id:
            for acc in available_accounts:
                if acc.id == previous_account_id:
                    logger.info(f"[sticky] 继续使用账号: {acc.id}")
                    return acc
            logger.debug(f"[sticky] 上次账号 {previous_account_id} 不可用，回退")

        # 回退到 free-first
        sorted_accounts = sorted(available_accounts, key=lambda x: x.priority, reverse=True)
        selected = sorted_accounts[0]
        logger.info(f"[sticky] 回退 free-first: {selected.id}")
        return selected
