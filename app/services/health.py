"""
厂商健康度信号（B2）——v0.6.0

进程内滑动窗口统计每个账号的调用结果（延迟/成功率/最近错误），
为路由决策和选号提供动态健康度依据。SQLite 单实例下进程级足够；
多实例部署时随企业组件池替换为 Redis（stores SPI 预留）。
"""
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

logger = logging.getLogger(__name__)

_WINDOW_SIZE = 100  # 每个账号保留最近 100 次调用样本
_WINDOW_SECONDS = 600  # 只统计最近 10 分钟


@dataclass
class HealthSample:
    """单次调用健康度样本"""

    success: bool
    latency_ms: int
    ts: float = field(default_factory=time.time)


@dataclass
class HealthStats:
    """账号健康度统计（滑动窗口）"""

    account_id: int
    samples: Deque[HealthSample] = field(default_factory=lambda: deque(maxlen=_WINDOW_SIZE))
    last_error: str = ""
    last_error_ts: float = 0.0

    @property
    def success_rate(self) -> float:
        """近 10 分钟成功率（0~1）；无样本返回 1.0（未知视为可用）"""
        cutoff = time.time() - _WINDOW_SECONDS
        recent = [s for s in self.samples if s.ts >= cutoff]
        if not recent:
            return 1.0
        return sum(1 for s in recent if s.success) / len(recent)

    @property
    def avg_latency_ms(self) -> float:
        """近 10 分钟平均延迟（ms）；无样本返回 0"""
        cutoff = time.time() - _WINDOW_SECONDS
        recent = [s for s in self.samples if s.ts >= cutoff]
        if not recent:
            return 0.0
        return sum(s.latency_ms for s in recent) / len(recent)

    @property
    def is_unhealthy(self) -> bool:
        """判定不健康：近 10 分钟样本数 >= 3 且成功率 < 0.5"""
        cutoff = time.time() - _WINDOW_SECONDS
        recent = [s for s in self.samples if s.ts >= cutoff]
        if len(recent) < 3:
            return False
        return self.success_rate < 0.5


class HealthTracker:
    """账号健康度跟踪器（进程内全局单例）"""

    def __init__(self):
        self._stats: Dict[int, HealthStats] = {}

    def record(self, account_id: int, success: bool, latency_ms: int, error: str = "") -> None:
        """记录一次调用结果"""
        stats = self._stats.setdefault(account_id, HealthStats(account_id=account_id))
        stats.samples.append(HealthSample(success=success, latency_ms=latency_ms))
        if not success and error:
            stats.last_error = error
            stats.last_error_ts = time.time()
        if success:
            stats.last_error = ""

    def get(self, account_id: int) -> Optional[HealthStats]:
        return self._stats.get(account_id)

    def snapshot(self) -> Dict[int, HealthStats]:
        """全量快照（省钱看板/调试用）"""
        return dict(self._stats)

    def reset(self) -> None:
        """清空全部统计（测试/维护用）"""
        self._stats.clear()


# 全局健康度跟踪器
health_tracker = HealthTracker()
