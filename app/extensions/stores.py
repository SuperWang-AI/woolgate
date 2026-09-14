"""
会话状态存储 SPI（A6 租户隔离预留）——v0.6.0

内置 SQLite 实现（现状不变）；企业版可注册 Redis 实现。
多租户下 session_id 必须带租户前缀 {tenant_id}:{session_id}，杜绝跨租户串数据。
详见 docs/extensions/06-tenant-isolation.md。
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from app.extensions.sdk import register_spi

if TYPE_CHECKING:
    from app.models.database import SessionState
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SPI_STORE = "store"


def build_scoped_session_id(tenant_id: Optional[str], session_id: str) -> str:
    """
    多租户会话 key：{tenant_id}:{session_id}；单租户（tenant_id 为空）原样返回。
    契约 06 第 2 节。
    """
    if tenant_id:
        return f"{tenant_id}:{session_id}"
    return session_id


class SessionStateStore(ABC):
    """会话状态存储 SPI"""

    name: str = "base"

    @abstractmethod
    async def get(self, scoped_session_id: str) -> Optional["SessionState"]:
        ...

    @abstractmethod
    async def save(self, state: "SessionState") -> None:
        ...


class SQLiteSessionStateStore(SessionStateStore):
    """SQLite 默认实现（现状行为）"""

    name = "sqlite"

    def __init__(self, db: "AsyncSession"):
        self.db = db

    async def get(self, scoped_session_id: str) -> Optional["SessionState"]:
        from sqlalchemy import select
        from app.models.database import SessionState

        result = await self.db.execute(
            select(SessionState).where(SessionState.session_id == scoped_session_id)
        )
        return result.scalar_one_or_none()

    async def save(self, state: "SessionState") -> None:
        self.db.add(state)
        await self.db.commit()


register_spi(SPI_STORE, "sqlite", "sqlite://builtin")  # 占位：SQLite 实现需绑定 db，由 SessionStateService 直连
