"""
轮询策略（对应现有 round_robin）

按 id 排序，用内存索引轮转。

索引持久化：使用类变量（进程级共享）。SQLite 单实例部署下，
Executor 每次请求新建 selector 实例也不会重置索引，轮询可真实生效。
重启进程后索引归零（可接受的已知限制；多 worker/多实例部署请改用 Redis 等外部存储）。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class RoundRobinSelector(AccountSelector):
    """轮询：按 id 排序，内存索引轮转（类变量持久索引）"""

    name = "round-robin"

    # 进程级共享索引：按虚拟模型名维护（跨实例持久，避免每请求重置）
    _index: dict[str, int] = {}

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
