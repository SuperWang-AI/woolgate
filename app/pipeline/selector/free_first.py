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

        # 注意：available_accounts 已由上游 _filter_available_accounts 按 ModelCatalog.model_name 正确过滤
        # 此处不再用 default_model_name 二次过滤（主从架构下一个账号有多个模型，default_model_name 仅为默认模型）
        candidates = available_accounts
        if model_name:
            logger.info(f"[free-first] 目标模型 {model_name}，候选账号 {len(candidates)} 个（上游已按 ModelCatalog 过滤）")

        # 按优先级降序排序（priority 已从界面退场，全为默认值时退化为 id 降序：新账号优先）
        sorted_accounts = sorted(candidates, key=lambda x: (x.priority, x.id), reverse=True)
        selected = sorted_accounts[0]
        logger.info(f"[free-first] 选中账号: {selected.id} (模型: {selected.default_model_name}, 优先级: {selected.priority})")
        return selected
