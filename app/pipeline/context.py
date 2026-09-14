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


class Stage:
    """管线阶段常量（插件插口与阶段计时用，v0.6.0）"""

    REQUEST = "request"
    CLASSIFY = "classify"
    ROUTE = "route"
    SELECT = "select"
    CONTEXT = "context"
    EXECUTE = "execute"
    RESPONSE = "response"


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
    session_id: str = ""  # 会话标识（从 X-Session-Id 头读取，缺省用 client_ip）

    # ── API Key 信息（企业化部署）──
    api_key_id: Optional[int] = None  # 匹配到的 ApiKey ID
    default_model: Optional[str] = None  # API Key 默认模型，None=向量/LLM 路由自动选择
    forced_model: Optional[str] = None  # 斜杠命令强制指定的模型（/qwen-plus 等）
    user_override_model: Optional[str] = None  # 请求头 X-Model-Preference 指定（v0.6.0，次高于 default_model）

    # ── 分类引擎输出（v0.6.0 组件化）──
    classify_engine: str = ""  # 实际使用的分类引擎：vector/llm/local/auto
    classify_decision: str = ""  # 分类器的人类可读决策说明

    # ── ① ModelRouter 输出 ──
    target_model: Optional[str] = None
    router_strategy: str = "off"
    router_decision: str = ""
    router_latency_ms: int = 0
    router_confidence: float = 0.0  # 路由置信度（向量相似度或 LLM 置信度）
    model_switched: bool = False  # 本次请求是否发生了模型切换（跨模型切换时强制摘要）
    current_model: Optional[str] = None  # 会话当前模型（从 SessionState 读取，供滞回判定）

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

    # ── 成本维度（v0.6.0，省钱看板）──
    estimated_cost: float = 0.0  # 估算金额（元），按预估 token × 单价
    actual_cost: float = 0.0  # 实际金额（元），按实际 token × 单价

    # ── 治理层（企业版）──
    tenant_id: Optional[str] = None

    # ── 降级标记（v0.6.0）──
    degraded: bool = False  # 本次请求是否发生了降级（分类失败/无可用账号回退等）
    degrade_reason: str = ""  # 降级原因描述

    # ── 插件命名空间（v0.6.0）──
    # key=插件注册名；插件只能读写自己的命名空间，互不可见、不落库
    extensions: Dict[str, Any] = field(default_factory=dict)

    # ── 阶段标记（v0.6.0，插口与阶段计时）──
    stage: str = ""  # 当前阶段，取值见 Stage
    stage_timings_ms: Dict[str, int] = field(default_factory=dict)  # {stage: 耗时ms}

    def to_log_dict(self) -> Dict[str, Any]:
        """导出为结构化日志字典（用于 RequestLog 和日志输出）"""
        return {
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "target_model": self.target_model,
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
            # ── v0.6.0 新增字段 ──
            "classify_engine": self.classify_engine,
            "degraded": self.degraded,
            "degrade_reason": self.degrade_reason,
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
        }


@dataclass
class SessionState:
    """
    会话级状态——ContextManager 和路由滞回判定依赖。

    按 session_id 缓存（初期 SQLite，可换 Redis）。
    """

    session_id: str
    current_model: Optional[str] = None
    current_account_id: Optional[int] = None
    summary: Optional[str] = None
    summary_version: int = 0
    turn_count: int = 0
    last_activity: datetime = field(default_factory=datetime.utcnow)

    def touch(self) -> None:
        """更新最后活跃时间和轮次"""
        self.last_activity = datetime.utcnow()
        self.turn_count += 1
