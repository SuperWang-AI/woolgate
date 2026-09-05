"""
账号调度策略接口（薅羊毛层）

从可用账号池中选择一个具体账号。
策略只负责"选哪个"，不负责"过滤可用账号"（过滤由管线统一处理）。
"""
from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.database import ModelAccount


class AccountSelector(ABC):
    """账号调度策略抽象基类"""

    name: str = "base"

    @abstractmethod
    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        """
        从可用账号中选择一个。

        Args:
            available_accounts: 已经过滤好的可用账号列表（启用、匹配模型、未冷却、额度充足）
            model_name: 虚拟模型名（轮询策略需要按模型维护索引）
            previous_account_id: 上一次使用的账号ID（粘性策略用，其他策略忽略）

        Returns:
            选中的账号，无可用账号返回 None
        """
        ...
