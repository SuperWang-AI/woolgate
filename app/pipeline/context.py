"""
管线上下文与会话状态

PipelineContext: 贯穿三层管线的中间数据对象，每层读写自己的字段
SessionState: 会话级状态（领域标签、当前账号、摘要），按 session_id 缓存
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.database import ModelAccount


@dataclass
class PipelineContext:
    """
    请求管线上下文——三层共享的中间数据对象。

    每层只读写自己的字段，不修改其他层的字段：
    - 输入层（api 填充）：request_id, client_ip, stream, original_messages...
    - ModelRouter 输出：domain_tag, target_model, router_*
    - AccountSelector 输出：account, selector_*, tried_account_ids, switch_count
    - ContextManager 输出：assembled_messages, context_*, summary_used
    - Executor 输出：prompt_tokens, completion_tokens, response_time_ms, status
    """

    # ── 输入（只读，由 api 层填充）──
    request_id: str
    client_ip: str
    stream: bool
    original_messages: List[Dict[str, Any]]
    requested_model: str
    kwargs: Dict[str, Any]
    estimated_tokens: int

    # ── ① ModelRouter 输出 ──
    domain_tag: Optional[str] = None
    target_model: Optional[str] = None
    router_strategy: str = "off"
    router_decision: str = ""
    router_latency_ms: int = 0

    # ── ② AccountSelector 输出 ──
    account: Optional["ModelAccount"] = None
    selector_strategy: str = "pin"
    selector_decision: str = ""
    tried_account_ids: List[int] = field(default_factory=list)
    switch_count: int = 0

    # ── ③ ContextManager 输出 ──
    assembled_messages: List[Dict[str, Any]] = field(default_factory=list)
    context_strategy: str = "passthrough"
    summary_used: bool = False
    context_latency_ms: int = 0

    # ── ④ Executor 输出 ──
    prompt_tokens: int = 0
    completion_tokens: int = 0
    response_time_ms: int = 0
    status: str = "success"
    error_message: Optional[str] = None

    # ── 治理层（企业版）──
    tenant_id: Optional[str] = None

    def to_log_dict(self) -> Dict[str, Any]:
        """导出为结构化日志字典（用于 RequestLog 和日志输出）"""
        return {
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "domain_tag": self.domain_tag,
            "router_strategy": self.router_strategy,
            "router_decision": self.router_decision,
            "router_latency_ms": self.router_latency_ms,
            "selector_strategy": self.selector_strategy,
            "selector_decision": self.selector_decision,
            "account_id": self.account.id if self.account else None,
            "switch_count": self.switch_count,
            "context_strategy": self.context_strategy,
            "summary_used": self.summary_used,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "response_time_ms": self.response_time_ms,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class SessionState:
    """
    会话级状态——ContextManager 和路由滞回判定依赖。

    按 session_id 缓存（初期 SQLite，可换 Redis）。
    """

    session_id: str
    current_domain: Optional[str] = None
    current_account_id: Optional[int] = None
    summary: Optional[str] = None
    summary_version: int = 0
    turn_count: int = 0
    last_activity: datetime = field(default_factory=datetime.utcnow)

    def touch(self) -> None:
        """更新最后活跃时间和轮次"""
        self.last_activity = datetime.utcnow()
        self.turn_count += 1
