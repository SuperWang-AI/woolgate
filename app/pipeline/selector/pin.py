"""
指定模型策略（pin）—— AccountSelector 默认策略

按请求级 header 或全局配置指定具体模型/账号，不做自动调度。
优先级：pin_account_id > pin_model > 回退 free-first。

请求级指定方式（第4步接入 Executor 后生效）：
    X-WoolGate-Pin-Model: kimi-k2.6
    X-WoolGate-Pin-Account: 4
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class PinSelector(AccountSelector):
    """指定模型：按配置的模型名或账号ID选择"""

    name = "pin"

    def __init__(self, pin_model: str = "", pin_account_id: int = 0):
        self.pin_model = pin_model
        self.pin_account_id = pin_account_id

    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        # 1. 优先按账号ID指定
        if self.pin_account_id and self.pin_account_id > 0:
            for acc in available_accounts:
                if acc.id == self.pin_account_id:
                    logger.info(f"[pin] 按账号ID选中: {acc.id}")
                    return acc
            logger.warning(f"[pin] 指定的账号ID {self.pin_account_id} 不在可用列表中，回退")

        # 2. 其次按模型名指定（上游 _filter_available_accounts 已按 ModelCatalog.model_name 过滤，直接选第一个即可）
        if self.pin_model:
            if available_accounts:
                selected = available_accounts[0]
                logger.info(f"[pin] 按模型名 {self.pin_model} 选中: {selected.id}（上游已按 ModelCatalog 过滤）")
                return selected
            logger.warning(f"[pin] 指定的模型 {self.pin_model} 不在可用列表中，回退")

        # 3. 都没指定或都没匹配到，回退到 free-first（按优先级选第一个）
        selected = self._pick_highest_priority(available_accounts)
        logger.info(f"[pin] 无指定，回退 free-first: {selected.id}")
        return selected
