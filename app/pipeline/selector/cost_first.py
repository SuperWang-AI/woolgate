"""
成本最低策略（cost-first）—— 企业版

按模型单价从低到高选择账号。
M1 阶段 ModelCatalog 价格表尚未启用，暂时按 priority 降序（与 free-first 行为一致）。
TODO(M2): 接入 ModelCatalog.input_price/output_price，按预估成本排序。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class CostFirstSelector(AccountSelector):
    """成本最低：M1 暂用 priority 代替，M2 接入 ModelCatalog 价格表"""

    name = "cost-first"

    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        # TODO(M2): 按 ModelCatalog 中的 input_price/output_price 计算预估成本排序
        # 当前暂按 priority 降序（与 free-first 行为一致）
        sorted_accounts = sorted(available_accounts, key=lambda x: x.priority, reverse=True)
        selected = sorted_accounts[0]
        logger.info(f"[cost-first] 选中账号: {selected.id} (M1暂用priority)")
        return selected
