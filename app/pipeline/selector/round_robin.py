"""
轮询策略（对应现有 round_robin）

按 id 排序，用数据库持久化索引轮转。

索引持久化：存储在 round_robin_state 表，重启后不丢失。
单实例 SQLite 部署下，每次请求读写一次数据库，性能可接受。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class RoundRobinSelector(AccountSelector):
    """轮询：按 id 排序，数据库持久化索引"""

    name = "round-robin"

    async def select_async(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        # 按 ID 排序保证顺序稳定
        sorted_accounts = sorted(available_accounts, key=lambda x: x.id)
        n = len(sorted_accounts)

        # 从数据库读上次索引
        from app.models.database import AsyncSessionLocal, RoundRobinState
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RoundRobinState).where(RoundRobinState.model_name == model_name)
            )
            state = result.scalar_one_or_none()

            if state is None:
                idx = 0
                state = RoundRobinState(model_name=model_name, last_index=0)
                session.add(state)
            else:
                idx = state.last_index % n

            selected = sorted_accounts[idx]

            # 更新索引
            state.last_index = (idx + 1) % n
            await session.commit()

        logger.info(f"[round-robin] 选中账号: {selected.id} (索引: {idx})")
        return selected
