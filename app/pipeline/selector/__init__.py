"""账号调度策略包（薅羊毛层）"""
from app.pipeline.selector.base import AccountSelector
from app.pipeline.selector.free_first import FreeFirstSelector
from app.pipeline.selector.round_robin import RoundRobinSelector
from app.pipeline.selector.pin import PinSelector
from app.pipeline.selector.sticky import StickySelector
from app.pipeline.selector.failover import FailoverSelector
from app.pipeline.selector.cost_first import CostFirstSelector

__all__ = [
    "AccountSelector",
    "FreeFirstSelector",
    "RoundRobinSelector",
    "PinSelector",
    "StickySelector",
    "FailoverSelector",
    "CostFirstSelector",
]
