"""
生命周期插口（hooks）——v0.6.0 组件化/插件化预留

9 个插口常量 + 钩子注册表。插口是"在正确时机调你"的挂载点，
不关心插件内部实现。详见 docs/extensions/02-hooks-spi.md。
"""
import logging
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

# ── 插口常量（9 个，契约 02 第 2 节）──
HOOK_REQUEST_STARTED = "request.started"
HOOK_CLASSIFY_AFTER = "classify.after"
HOOK_ROUTE_BEFORE = "route.before"
HOOK_ROUTE_AFTER = "route.after"
HOOK_SELECT_AFTER = "select.after"
HOOK_CONTEXT_AFTER = "context.after"
HOOK_EXECUTE_AFTER = "execute.after"
HOOK_REQUEST_FINISHED = "request.finished"
HOOK_ERROR_OCCURRED = "error.occurred"

ALL_HOOKS: tuple = (
    HOOK_REQUEST_STARTED,
    HOOK_CLASSIFY_AFTER,
    HOOK_ROUTE_BEFORE,
    HOOK_ROUTE_AFTER,
    HOOK_SELECT_AFTER,
    HOOK_CONTEXT_AFTER,
    HOOK_EXECUTE_AFTER,
    HOOK_REQUEST_FINISHED,
    HOOK_ERROR_OCCURRED,
)

# 只允许 after 类钩子修改决策字段（契约 02 第 3 节：before 可阻断，after 只可观测/写命名空间）
MUTABLE_HOOKS: set = {
    HOOK_CLASSIFY_AFTER,
    HOOK_ROUTE_AFTER,
    HOOK_SELECT_AFTER,
    HOOK_CONTEXT_AFTER,
    HOOK_EXECUTE_AFTER,
}

# 钩子函数签名：async (ctx) -> None
HookFn = Callable[["Any"], Awaitable[None]]


class HookBlocked(Exception):
    """before 类钩子主动拒绝请求时抛出（契约 03 第 6 节）"""

    def __init__(self, reason: str = "blocked by hook", status_code: int = 400):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


class HookRegistry:
    """进程内钩子注册表：event -> [(priority, order, fn)]"""

    def __init__(self):
        self._hooks: Dict[str, List[tuple]] = {}
        self._order = 0  # 同优先级按注册顺序稳定排序

    def register(self, event: str, fn: HookFn, priority: int = 1000) -> None:
        """注册钩子：priority 越小越先执行；同优先级按注册顺序"""
        if event not in ALL_HOOKS:
            logger.warning(f"[hooks] 未知插口名 {event}，忽略注册")
            return
        self._order += 1
        self._hooks.setdefault(event, []).append((priority, self._order, fn))
        self._hooks[event].sort(key=lambda x: (x[0], x[1]))
        logger.info(f"[hooks] 已注册插口 {event}（priority={priority}）")

    def has(self, event: str) -> bool:
        return bool(self._hooks.get(event))

    def snapshot(self, event: str) -> List[HookFn]:
        """返回按优先级排序的钩子列表（空列表表示无钩子，零开销路径）"""
        return [fn for _, _, fn in self._hooks.get(event, [])]


# 全局钩子注册表（单进程单事件循环，FastAPI 部署下安全）
hook_registry = HookRegistry()
