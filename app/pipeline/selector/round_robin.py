"""
轮询策略（对应现有 round_robin）

按 id 排序，用内存索引轮转。
行为与现有 AccountRouter._select_round_robin 完全一致。

注意：现有实现使用实例变量索引，每次请求新建 AccountRouter 时索引会重置。
这是已知限制，后续可改为类变量或 Redis 持久化。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class RoundRobinSelector(AccountSelector):
    """轮询：按 id 排序，内存索引轮转"""

    name = "round-robin"

    def __init__(self):
        # 按虚拟模型名维护轮询索引（与现有实现一致，实例变量）
        self._index: dict[str, int] = {}

    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        # 按 ID 排序保证顺序稳定（与现有 _select_round_robin 完全一致）
        sorted_accounts = sorted(available_accounts, key=lambda x: x.id)

        if model_name not in self._index:
            self._index[model_name] = 0

        idx = self._index[model_name] % len(sorted_accounts)
        selected = sorted_accounts[idx]

        # 更新索引
        self._index[model_name] = (idx + 1) % len(sorted_accounts)

        logger.info(f"[round-robin] 选中账号: {selected.id} (索引: {idx})")
        return selected
