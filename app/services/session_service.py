"""
会话状态服务——SessionState 的加载、创建、更新、持久化。

按 session_id 维护会话级状态：当前领域、当前账号、对话摘要、轮次计数。
VectorRouter 的滞回判定和 SummaryManager 的摘要复用都依赖此服务。
"""
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import SessionState as SessionStateModel
from app.pipeline.context import SessionState

logger = logging.getLogger(__name__)


class SessionStateService:
    """会话状态服务（SQLite 持久化）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, session_id: str) -> SessionState:
        """获取或创建会话状态"""
        if not session_id:
            # 无 session_id 时返回临时状态（不持久化）
            return SessionState(session_id="")

        result = await self.db.execute(
            select(SessionStateModel).where(SessionStateModel.session_id == session_id)
        )
        model = result.scalar_one_or_none()

        if model:
            return SessionState(
                session_id=model.session_id,
                current_model=model.current_model,
                current_account_id=model.current_account_id,
                summary=model.summary,
                summary_version=model.summary_version,
                turn_count=model.turn_count,
                last_activity=model.last_activity,
            )

        # 创建新会话
        model = SessionStateModel(session_id=session_id)
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        logger.info(f"创建会话状态: {session_id}")
        return SessionState(session_id=session_id)

    async def update(
        self,
        session_id: str,
        current_model: Optional[str] = None,
        current_account_id: Optional[int] = None,
        summary: Optional[str] = None,
        increment_turn: bool = False,
    ) -> None:
        """更新会话状态（仅更新非 None 字段）"""
        if not session_id:
            return

        result = await self.db.execute(
            select(SessionStateModel).where(SessionStateModel.session_id == session_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return

        if current_model is not None:
            model.current_model = current_model
        if current_account_id is not None:
            model.current_account_id = current_account_id
        if summary is not None:
            model.summary = summary
            model.summary_version += 1
        if increment_turn:
            model.turn_count += 1

        await self.db.commit()
        logger.debug(f"更新会话状态: {session_id}, model={current_model}, turn={model.turn_count}")

    async def increment_turn(self, session_id: str) -> None:
        """增加会话轮次"""
        await self.update(session_id, increment_turn=True)

    async def set_model(self, session_id: str, model: str) -> None:
        """设置当前模型"""
        await self.update(session_id, current_model=model)

    async def set_account(self, session_id: str, account_id: int) -> None:
        """设置当前账号（会话粘性用）"""
        await self.update(session_id, current_account_id=account_id)

    async def set_summary(self, session_id: str, summary: str) -> None:
        """设置对话摘要"""
        await self.update(session_id, summary=summary)
