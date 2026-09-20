"""
成本最优策略（cost-first）—— 选号排序主策略

排序规则（产品确认 A4-4）：
1. 免费优先：该账号下目标模型显式价格为 0 → 最优先
2. 同模型比价：有价格（>0）的按单价升序，低价先用
3. 余额/健康度：比价后再比剩余额度，额度多者优先
4. id 降序：同分兜底，新加的账号优先（用户对新模型有期待）

价格维度 = 账号 + 模型（ModelCatalog 行），由 executor 在调用前注入
`_cost_input` / `_cost_output` 临时属性（cost-first 专用，不落库）。
优先级（priority）字段已从界面退场，仅作历史兼容，不再参与排序。
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from app.pipeline.selector.base import AccountSelector

if TYPE_CHECKING:
    from app.models.database import ModelAccount

logger = logging.getLogger(__name__)


class CostFirstSelector(AccountSelector):
    """成本最优：免费优先 → 同模型比价 → 余额 → id 降序"""

    name = "cost-first"

    def select(
        self,
        available_accounts: List["ModelAccount"],
        model_name: str = "",
        previous_account_id: Optional[int] = None,
    ) -> Optional["ModelAccount"]:
        if not available_accounts:
            return None

        # 注意：available_accounts 已由上游 _filter_available_accounts 按 ModelCatalog.model_name 正确过滤
        # 此处不再用 default_model_name 二次过滤（主从架构下一个账号有多个模型）
        candidates = available_accounts
        if model_name:
            logger.info(f"[cost-first] 目标模型 {model_name}，候选账号 {len(candidates)} 个（上游已按 ModelCatalog 过滤）")

        if not candidates:
            return None

        selected = sorted(candidates, key=self._rank)[0]
        inp = getattr(selected, "_cost_input", None)
        logger.info(
            f"[cost-first] 选中账号: {selected.id} ({selected.vendor}, 模型: {selected.default_model_name}, "
            f"价格: {inp if inp is not None else '未知'})"
        )
        return selected

    def _rank(self, a: "ModelAccount") -> tuple:
        """排序键（升序，小者优先）"""
        inp = getattr(a, "_cost_input", None)
        out = getattr(a, "_cost_output", None)

        # 免费优先：显式 0/0 → L0；有价 → L1；未知 → L2（不冒险优先）
        if inp is not None and out is not None and inp == 0 and out == 0:
            level, price = 0, 0.0
        elif (inp is not None and inp > 0) or (out is not None and out > 0):
            level, price = 1, (inp if inp is not None else float("inf"))
        else:
            level, price = 2, float("inf")

        # 学习型选号：历史有效成本（考虑成功率）
        # 有历史数据 → 按有效成本升序；无历史数据 → 排在有数据的后面（先试新账号再给信号）
        eff = getattr(a, "_effective_cost", None)
        eff_key = eff if eff is not None else float("inf")

        # 余额/健康度：额度多者优先（None 视为 0）
        bal = getattr(a, "balance_remaining", None)
        bal = bal if bal is not None else 0.0

        # id 降序：新加的账号优先
        return (level, eff_key, price, -bal, -a.id)
