# WoolGate 架构设计文档

> **版本**: v1.0（2026-09-05）
> **状态**: 设计定稿，待实施
> **阶段**: M1 · 架构重构
> **关联**: MEMORY.md / Notion「WoolGate 架构演进笔记」

---

## 一、现状分析

### 1.1 当前架构

```
客户端请求 (model="chat", messages)
        │
        ▼
  api.py /v1/chat/completions
        │
        ├─ 每日余额同步（异步，不阻塞）
        │
        ├─ AccountRouter.select_account()
        │     ├─ 会话粘性（查最近10分钟成功日志）
        │     ├─ 筛选可用账号（启用+匹配虚拟模型+冷却+额度）
        │     └─ 策略选择（sequential / round_robin）
        │
        ├─ 流式: stream_with_failover() → stream_account() → llm_client
        │     （3次重试，输出前失败可切换账号）
        │
        └─ 非流式: 循环3次 → non_stream_handler() → llm_client
              （失败标记冷却，换下一个账号）
```

### 1.2 现有模块职责

| 模块 | 职责 | 关键类/函数 |
|---|---|---|
| `api.py` | 请求入口、鉴权、重试循环、记账、日志 | `chat_completions`, `stream_with_failover`, `stream_account`, `non_stream_handler` |
| `router.py` | 账号选择、会话粘性、额度检查、冷却、记账 | `AccountRouter` |
| `llm_client.py` | 上游 LLM 调用（httpx 流式/非流式） | `LLMClient` |
| `balance.py` | 厂商余额接口调用 | `fetch_balance` |
| `scheduler.py` | 定时任务（每日重置、日志清理） | `reset_daily_quota`, `clean_old_logs` |
| `models/database.py` | 数据模型 | `SystemConfig`, `ModelAccount`, `RequestLog` |

### 1.3 现有问题清单

| # | 问题 | 影响 |
|---|---|---|
| P1 | **无模型路由层**：只有账号调度（薅羊毛），没有"选羊"（按语义选模型/领域） | 无法实现智能路由，所有账号按同一虚拟模型 `chat` 平级竞争 |
| P2 | **无上下文管理层**：messages 直接透传，无摘要/滑动窗口 | 长会话超窗口、成本高、跨模型切换丢失上下文 |
| P3 | **策略硬编码**：`sequential`/`round_robin` 是 if-elif，无策略接口 | 新增策略（cost-first、vector、llm）需改核心代码 |
| P4 | **重试逻辑重复**：流式 `stream_with_failover` 和非流式 `chat_completions` 循环各一套 | 维护成本高，行为不一致风险 |
| P5 | **记账/日志重复**：`stream_account` 和 `non_stream_handler` 各写一套记账+日志 | 代码冗余 |
| P6 | **观测不足**：`RequestLog` 只有 account_id/vendor/model_name，无路由决策、领域标签、切换次数 | 无法回溯"为什么选了这个账号"，无法做成本分析 |
| P7 | **无多租户**：全局单 Bearer Token，无 tenant 隔离 | 无法企业级部署 |
| P8 | **无供应目录抽象**：账号=模型，无"供应项"概念（价格/能力标签/可用性） | 无法平台化（商户入驻） |

---

## 二、目标架构：三层策略管线

### 2.1 架构总览

```
客户端请求 (model="chat", messages, stream=True/False)
        │
        ▼
┌─────────────────────────────────────────────────┐
│              请求管线 Pipeline                    │
│                                                  │
│  ① ModelRouter（选羊）                           │
│     输入: messages + 配置                        │
│     输出: domain_tag（领域标签）+ target_model   │
│     策略: off / rules / vector / llm             │
│                                                  │
│  ② AccountSelector（薅羊毛）                     │
│     输入: domain_tag + 可用账号池 + 配置         │
│     输出: ModelAccount（具体账号）                │
│     策略: free-first / cost-first / sticky       │
│                                                  │
│  ③ ContextManager（上下文管理）                  │
│     输入: 原始 messages + 会话状态               │
│     输出: 组装后的 messages（摘要+窗口+当前）    │
│     策略: passthrough / window / summary         │
│                                                  │
│  ④ Executor（执行层，现有 llm_client）           │
│     流式转发 + 失败切换 + 输出规范化             │
│                                                  │
│  ⑤ Observer（观测，贯穿全管线）                  │
│     记录: 领域标签/路由决策/账号/token/耗时      │
└─────────────────────────────────────────────────┘
        │
        ▼
   客户端响应（SSE 流 / JSON）

治理层（企业版激活，横切）:
  - 多租户 tenant_id 鉴权与隔离
  - 配额预算（按租户限流/停服）
  - 审计日志（独立于请求日志）
  - 账单汇总（按租户/按账号）
```

### 2.2 核心原则

1. **三层串行是管线**：① → ② → ③ → ④，每层输出作为下层输入，中间通过 `PipelineContext` 传递
2. **每层策略可插拔**：策略实现统一接口，通过配置选择，新增策略不改核心代码
3. **模式 = 配置包**：开源版/企业版不是两套代码，是各层策略的不同组合 + 治理层开关
4. **增量重构**：不推翻现有代码，先抽接口、再迁移逻辑、最后替换入口
5. **观测先行**：每次请求的路由决策必须可追溯，为未来账单/分析打底

---

## 三、核心数据对象

### 3.1 PipelineContext（管线上下文）

贯穿全管线的中间数据对象，每层读写自己的字段，不修改其他层的字段。

```python
@dataclass
class PipelineContext:
    """请求管线上下文——三层共享的中间数据"""

    # ── 输入（只读，由 api 层填充）──
    request_id: str                    # 请求唯一 ID（UUID，用于日志关联）
    client_ip: str
    stream: bool
    original_messages: list[dict]      # 客户端原始 messages（不修改）
    requested_model: str               # 客户端请求的虚拟模型名（如 "chat"）
    kwargs: dict                       # temperature/max_tokens/top_p 等
    estimated_tokens: int

    # ── ① ModelRouter 输出 ──
    domain_tag: Optional[str] = None   # 领域标签，如 "code" / "general" / "creative"
    target_model: Optional[str] = None # 目标真实模型名（路由层决定，None=不限制）
    router_strategy: str = "off"       # 实际使用的路由策略
    router_decision: str = ""          # 决策说明（用于日志）
    router_latency_ms: int = 0

    # ── ② AccountSelector 输出 ──
    account: Optional["ModelAccount"] = None
    selector_strategy: str = "sticky"  # 实际使用的调度策略
    selector_decision: str = ""
    tried_account_ids: list[int] = field(default_factory=list)
    switch_count: int = 0              # 本次请求切换账号次数

    # ── ③ ContextManager 输出 ──
    assembled_messages: list[dict] = field(default_factory=list)  # 实际发给上游的 messages
    context_strategy: str = "passthrough"
    summary_used: bool = False         # 是否使用了摘要压缩
    context_latency_ms: int = 0

    # ── ④ Executor 输出 ──
    prompt_tokens: int = 0
    completion_tokens: int = 0
    response_time_ms: int = 0
    status: str = "success"            # success / failed
    error_message: Optional[str] = None

    # ── 治理层（企业版）──
    tenant_id: Optional[str] = None    # 租户 ID（None=单租户模式）
```

### 3.2 会话状态（SessionState）

ContextManager 依赖的会话级状态，按 `session_id` 缓存（内存或 Redis）。

```python
@dataclass
class SessionState:
    session_id: str
    current_domain: Optional[str] = None       # 当前领域标签（用于滞回判定）
    current_account_id: Optional[int] = None   # 当前账号（会话粘性）
    summary: Optional[str] = None              # 异步维护的对话摘要
    summary_version: int = 0                   # 摘要版本号，每次更新+1
    last_activity: datetime = field(default_factory=datetime.utcnow)
    turn_count: int = 0                        # 会话轮次
```

---

## 四、各层接口定义

### 4.1 ModelRouter（模型路由层 · 选羊）

```python
class ModelRouter(ABC):
    """模型路由策略接口——根据消息语义决定领域标签和目标模型"""

    name: str  # 策略标识：off / rules / vector / llm

    @abstractmethod
    async def route(self, ctx: PipelineContext) -> None:
        """
        执行路由决策，结果写入 ctx.domain_tag / ctx.target_model / ctx.router_*

        规则：
        - 不修改 ctx.original_messages
        - 不做账号选择（那是 AccountSelector 的事）
        - 决策过程必须可追溯（写入 ctx.router_decision）
        """
        ...

    @abstractmethod
    async def detect_drift(self, ctx: PipelineContext, session: SessionState) -> bool:
        """
        检测话题漂移（会话中使用）。
        返回 True 表示需要重新路由（切换领域模型）。
        仅 vector/llm 策略有意义，off/rules 返回 False。
        """
        ...
```

**内置策略实现：**

| 策略 | 类名 | 说明 | 适用版本 |
|---|---|---|---|
| `off` | `OffRouter` | 不路由，domain_tag=None，所有账号平级 | 开源/企业 |
| `rules` | `RulesRouter` | 关键词/正则匹配 → 领域标签（配置化关键词表） | 开源/企业 |
| `vector` | `VectorRouter` | embedding 余弦相似度 + 领域原型向量 + 滞回阈值 | 企业 |
| `llm` | `LLMRouter` | 便宜小模型分类 → 领域标签 | 企业 |

**RouterConfig（路由配置，存 SystemConfig.router_config_json）：**

```python
@dataclass
class RouterConfig:
    strategy: str = "off"                    # off / rules / vector / llm
    fallback_domain: str = "general"         # 未命中时的兜底领域

    # ── rules 策略：关键词/正则映射 ──
    # 规则数据存在数据库表 router_rule（见 7.5），管理界面可维护；
    # 也支持从 JSON 配置文件批量导入（启动时或手动触发 import）。
    # 匹配优先级：正则(pattern) > 关键词(keywords)，同类型按 priority 降序。
    rules_match_mode: str = "any"            # any=命中任一关键词即匹配 / all=全部命中

    # ── vector 策略：Embedding 后端配置 ──
    embedding_backend: str = "cloud"         # cloud（云端API） / local（本地插件，选装）

    # · cloud 配置
    embedding_cloud_provider: str = "aliyun" # aliyun / openai / custom
    embedding_cloud_base_url: str = ""       # custom 时必填，如 https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding
    embedding_cloud_api_key: str = ""        # 加密存储（同 ModelAccount.api_key_encrypted 机制）
    embedding_cloud_model: str = "text-embedding-v3"
    embedding_cloud_input_field: str = "input"          # 请求体中输入文本的字段名
    embedding_cloud_output_path: str = "output.embeddings[0].embedding"  # 响应中向量的 JSONPath
    embedding_cloud_dimensions: int = 1024   # 向量维度（用于校验）

    # · local 配置（选装插件，未安装不自动下载）
    embedding_local_plugin: str = "bge-small-zh"  # 插件包标识
    embedding_local_model_path: str = ""     # 本地模型文件路径（插件安装后填充）
    embedding_local_installed: bool = False  # 是否已安装（管理界面显示安装状态，未安装时 vector 策略自动降级为 rules）

    # · 领域原型与阈值
    domain_prototypes: dict[str, str] = field(default_factory=dict)  # 领域→原型描述文本（如 "code": "编程、代码、调试、算法"）
    domain_prototype_vectors: dict[str, list[float]] = field(default_factory=dict)  # 原型向量缓存（离线计算后存入，避免每次重算）
    threshold_high: float = 0.75             # 切入新领域阈值（余弦相似度 ≥ 此值才切换）
    threshold_low: float = 0.60              # 切走当前领域阈值（滞回：低于此值才考虑离开当前领域）

    # ── llm 策略：分类模型配置 ──
    classifier_deploy: str = "cloud"         # cloud（云端账号） / local（本地 Ollama）
    classifier_account_id: int = 0           # cloud：指定一个 ModelAccount.id（用该账号的模型做分类）
    classifier_local_model: str = ""         # local：Ollama 模型名，如 qwen2.5:1.5b
    classifier_prompt: str = (               # 分类 prompt 模板，{text} 替换为用户当前请求
        "你是一个对话分类器。请将以下用户请求分类到以下领域之一：{domains}。"
        "只输出领域名称，不要解释。\n\n用户请求：{text}"
    )
    classifier_max_tokens: int = 50          # 分类响应最大 token（分类只需要一个词）
```

### 4.2 AccountSelector（账号调度层 · 薅羊毛）

```python
class AccountSelector(ABC):
    """账号调度策略接口——从可用账号池中选一个具体账号"""

    name: str  # free-first / cost-first / sticky / failover

    @abstractmethod
    async def select(
        self,
        ctx: PipelineContext,
        available_accounts: list["ModelAccount"],
        session: Optional[SessionState],
    ) -> Optional["ModelAccount"]:
        """
        从可用账号中选择一个。

        输入:
          - available_accounts: 已通过基础筛选（启用/匹配/冷却/额度）的账号池
          - session: 会话状态（用于粘性）
        输出:
          - 选中的 ModelAccount，无可用返回 None

        规则：
          - 不做基础筛选（由管线统一做）
          - 不修改 messages（那是 ContextManager 的事）
          - 决策写入 ctx.selector_decision
        """
        ...
```

**内置策略实现：**

| 策略 | 类名 | 说明 | 适用版本 |
|---|---|---|---|
| `pin` | `PinSelector` | **指定模型**——按请求参数或系统配置指定具体模型/账号，不做自动调度。优先读请求 header `X-WoolGate-Pin-Model`，其次读系统配置 `pin_model`；在匹配该模型的启用账号中按优先级选一个；指定模型无可用账号时返回 None（不自动切换到其他模型） | 开源/企业 |
| `free-first` | `FreeFirstSelector` | 免费额度优先耗尽（现有 sequential 逻辑） | 开源/企业 |
| `cost-first` | `CostFirstSelector` | 按成本最低选择（需 currency_rate） | 企业 |
| `sticky` | `StickySelector` | 会话粘性优先（现有 `_infer_previous_account`） | 开源/企业 |
| `failover` | `FailoverSelector` | 主备模式，主账号失败才切备 | 企业 |

> **默认策略说明**：`pin`（指定模型）作为最直观的默认选项提供——用户明确知道要用哪个模型时直接指定，系统不做多余调度；未指定时回退到 `free-first`（薅羊毛）。管理界面中"调度策略"下拉框第一个就是"指定模型"。

**PinSelector 配置：**

```python
@dataclass
class PinSelectorConfig:
    pin_model: str = ""          # 全局默认指定的真实模型名（如 "kimi-k2.6"），空=不全局指定
    pin_account_id: int = 0      # 全局默认指定的账号 ID（0=不指定账号，只指定模型）
    allow_override: bool = True  # 允许请求级 header 覆盖全局配置
```

请求级指定方式（客户端无需改代码，通过 header 传递）：
```
X-WoolGate-Pin-Model: kimi-k2.6        # 指定模型
X-WoolGate-Pin-Account: 4              # 指定账号（可选，优先级高于模型）
```

**账号池筛选（管线统一，不属于策略）：**

```python
async def filter_available_accounts(
    session: AsyncSession,
    ctx: PipelineContext,
) -> list[ModelAccount]:
    """统一账号池筛选：启用 + 匹配虚拟模型/目标模型 + 冷却 + 额度"""
    # 1. 启用 + 匹配 virtual_model（或 target_model 如果路由层指定了）
    # 2. 不在冷却中
    # 3. 额度充足（统一余额逻辑）
    # 4. 排除 ctx.tried_account_ids（已失败的）
    ...
```

### 4.3 ContextManager（上下文管理层）

```python
class ContextManager(ABC):
    """上下文管理策略接口——组装发给上游的 messages"""

    name: str  # passthrough / window / summary

    @abstractmethod
    async def assemble(
        self,
        ctx: PipelineContext,
        session: Optional[SessionState],
    ) -> list[dict]:
        """
        组装实际发给上游的 messages，写入 ctx.assembled_messages。

        passthrough: 直接返回 ctx.original_messages
        window: 保留最近 N 轮原文，超出部分丢弃
        summary: 早期对话摘要 + 最近 N 轮原文 + 当前请求
        """
        ...

    @abstractmethod
    async def update_summary(
        self,
        session: SessionState,
        messages: list[dict],
        response: str,
    ) -> None:
        """
        异步更新会话摘要（请求完成后后台调用，不阻塞响应）。
        仅 summary 策略有实际实现，其他策略为空操作。
        """
        ...
```

**ContextConfig：**

```python
@dataclass
class ContextConfig:
    strategy: str = "passthrough"       # passthrough / window / summary
    window_turns: int = 10              # 滑动窗口保留最近 N 轮
    summary_model_account_id: int = 0   # 摘要用的模型账号（0=用当前账号）
    summary_trigger_tokens: int = 4000  # 超过这个 token 数触发摘要更新
    summary_trigger_turns: int = 5      # 每 N 轮触发一次摘要更新
```

### 4.4 Executor（执行层，现有 llm_client 封装）

```python
class Executor:
    """执行层——统一流式/非流式，封装失败切换与记账"""

    async def execute(
        self,
        ctx: PipelineContext,
        db: AsyncSession,
    ) -> AsyncGenerator[dict, None] | dict:
        """
        统一执行入口。

        - 流式: 返回 AsyncGenerator，内部管理账号切换
        - 非流式: 返回完整响应 dict
        - 失败切换逻辑统一在这里（不再分两套）
        - 记账和日志统一在这里（不再分两套）
        """
        ...
```

**关键改进：流式/非流式共用同一套重试循环**，通过 `ctx.stream` 区分输出方式。

---

## 五、配置 Schema

### 5.1 SystemConfig 扩展（数据库单行配置）

在现有 `SystemConfig` 表基础上新增字段（`_ensure_columns` 幂等补列）：

```python
# ── 模型路由（选羊）──
router_strategy = Column(String(20), default="off",
    comment="off/rules/vector/llm")
router_config_json = Column(JSON, nullable=True,
    comment="RouterConfig 序列化（领域原型、阈值、关键词表等）")

# ── 账号调度（薅羊毛）──
selector_strategy = Column(String(20), default="pin",
    comment="pin/free-first/cost-first/sticky/failover（默认 pin=指定模型）")
selector_config_json = Column(JSON, nullable=True,
    comment="SelectorConfig 序列化（pin_model/pin_account_id 等）")

# ── 上下文管理 ──
context_strategy = Column(String(20), default="passthrough",
    comment="passthrough/window/summary")
context_config_json = Column(JSON, nullable=True,
    comment="ContextConfig 序列化")

# ── 治理层（企业版）──
tenant_enabled = Column(Boolean, default=False,
    comment="多租户开关（企业版）")
budget_enabled = Column(Boolean, default=False,
    comment="配额预算开关（企业版）")

# ── 版本标识 ──
edition = Column(String(20), default="opensource",
    comment="opensource/enterprise（决定哪些策略可用）")
```

### 5.2 配置加载

```python
@dataclass
class PipelineConfig:
    """从 SystemConfig 反序列化的管线配置"""
    router_strategy: str
    router_config: RouterConfig
    selector_strategy: str
    context_strategy: str
    context_config: ContextConfig
    edition: str  # opensource / enterprise

    @classmethod
    async def load(cls, session: AsyncSession) -> "PipelineConfig":
        """从数据库加载，缓存 60 秒（配置变更不频繁）"""
        ...
```

### 5.3 开源/企业功能边界

| 能力 | 开源版 (opensource) | 企业版 (enterprise) |
|---|---|---|
| ModelRouter | off / rules | off / rules / vector / llm |
| AccountSelector | free-first / sticky | 全部 |
| ContextManager | passthrough | 全部 |
| 治理层 | 关闭 | 多租户/预算/审计/账单 |
| 配置方式 | 管理界面手动 | 管理界面 + API |

**版本切换**：修改 `SystemConfig.edition` 即可，无需改代码或重启。企业版策略在开源版下自动降级为最接近的开源策略（如 vector→rules，summary→passthrough）。

---

## 六、请求流程（统一管线）

### 6.1 流式请求

```
api.py chat_completions(stream=True)
  │
  ├─ 1. 构建 PipelineContext（request_id, messages, kwargs...）
  ├─ 2. 异步触发每日余额同步（现有逻辑不变）
  ├─ 3. 获取/创建 SessionState（按 session_id 或 messages 哈希）
  │
  ├─ 4. ModelRouter.route(ctx)         ← 新增
  │     └─ 写入 ctx.domain_tag, ctx.target_model
  │
  ├─ 5. AccountSelector 循环（最多 max_retry_count 次）:
  │     ├─ filter_available_accounts(ctx)
  │     ├─ selector.select(ctx, pool, session)
  │     ├─ ContextManager.assemble(ctx, session)   ← 新增
  │     ├─ Executor 流式消费
  │     │     ├─ 成功 → yield chunks → 记账+日志 → return
  │     │     └─ 输出前失败 → 标记冷却 → ctx.tried_account_ids.add → continue
  │     └─ 输出后失败 → 错误事件结束（不能切换）
  │
  ├─ 6. 异步触发 ContextManager.update_summary()  ← 新增（summary 策略）
  └─ 7. StreamingResponse 返回
```

### 6.2 非流式请求

同 6.1，区别仅在 Executor 内部返回完整 dict 而非 generator。

### 6.3 关键变化对照

| 环节 | 现有 | 重构后 |
|---|---|---|
| 账号选择 | `AccountRouter.select_account()` 内部含粘性+筛选+策略 | 粘性→Selector 策略，筛选→管线统一，策略→Selector 接口 |
| 重试循环 | 流式 `stream_with_failover` + 非流式 `chat_completions` 循环 | 统一在 `Executor.execute()` |
| 记账+日志 | `stream_account` / `non_stream_handler` 各一套 | 统一在 `Executor` 的 finally |
| 模型路由 | 无 | `ModelRouter` 层 |
| 上下文管理 | 直传 | `ContextManager` 层 |
| 会话状态 | 查 RequestLog 推断（10分钟窗口） | `SessionState` 显式管理（内存/Redis） |

---

## 七、数据模型变更

### 7.1 RequestLog 扩展（观测埋点）

```python
# 新增字段（_ensure_columns 幂等补列，旧数据为 NULL）
request_id = Column(String(64), nullable=True, comment="请求唯一ID，关联管线上下文")
domain_tag = Column(String(50), nullable=True, comment="路由领域标签")
router_strategy = Column(String(20), nullable=True, comment="实际路由策略")
selector_strategy = Column(String(20), nullable=True, comment="实际调度策略")
context_strategy = Column(String(20), nullable=True, comment="实际上下文策略")
switch_count = Column(Integer, default=0, comment="本次请求切换账号次数")
summary_used = Column(Boolean, default=False, comment="是否使用了摘要压缩")
tenant_id = Column(String(64), nullable=True, comment="租户ID（企业版）")
```

### 7.2 新增表：SessionState（会话状态）

```python
class SessionState(Base):
    """会话状态表（也可改用 Redis，初期用 SQLite）"""
    __tablename__ = "session_state"
    session_id = Column(String(64), primary_key=True)
    current_domain = Column(String(50), nullable=True)
    current_account_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    summary_version = Column(Integer, default=0)
    turn_count = Column(Integer, default=0)
    last_activity = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
```

> 初期用 SQLite，会话量大后可换 Redis（接口不变）。

### 7.3 新增表：ModelCatalog（供应目录 · 平台化预留）

```python
class ModelCatalog(Base):
    """模型供应目录——账号/模型抽象为供应项（平台化地基）"""
    __tablename__ = "model_catalog"
    id = Column(Integer, primary_key=True)
    vendor = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    display_name = Column(String(100), nullable=True, comment="展示名")
    capability_tags = Column(JSON, nullable=True, comment="能力标签: ['code','chat','vision']")
    domain_tags = Column(JSON, nullable=True, comment="适用领域: ['general','code']")
    input_price = Column(Float, nullable=True, comment="输入单价 元/1M token")
    output_price = Column(Float, nullable=True, comment="输出单价 元/1M token")
    context_window = Column(Integer, nullable=True, comment="上下文窗口")
    is_active = Column(Boolean, default=True)
    description = Column(Text, nullable=True)
```

> M1 阶段建表但不强制使用，M4/M5 阶段启用。账号表通过 `model_name` 关联目录。

### 7.4 新增表：RouterRule（路由规则表 · rules 策略用）

```python
class RouterRule(Base):
    """路由规则表——rules 策略的关键词/正则映射，管理界面可维护"""
    __tablename__ = "router_rule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain_tag = Column(String(50), nullable=False, comment="目标领域标签，如 code/general/creative")
    keywords = Column(JSON, nullable=False, comment="关键词列表，如 ['python','代码','调试']")
    pattern = Column(String(500), nullable=True, comment="正则表达式（可选，优先级高于关键词）")
    priority = Column(Integer, default=50, comment="优先级（数值越大越先匹配）")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**匹配逻辑**：
1. 加载所有 `is_active=True` 的规则，按 `priority` 降序
2. 对每条规则：先检查 `pattern`（正则匹配用户当前请求文本），命中即返回该 `domain_tag`
3. 无正则或未命中：检查 `keywords`，按 `rules_match_mode`（any/all）判断
4. 全部未命中：返回 `fallback_domain`

**批量导入**：支持从 JSON 文件导入（格式 `[{"domain_tag":"code","keywords":["python"]}, ...]`），用于初始化或备份恢复。

### 7.5 tenant_id 字段（企业版地基）

所有业务表（`ModelAccount`, `RequestLog`, `SessionState`）预留 `tenant_id` 列，M1 阶段允许 NULL（单租户模式），M4 阶段启用。

---

## 八、目录结构调整

```
app/
├── pipeline/                    ← 新增：管线核心
│   ├── __init__.py
│   ├── context.py               # PipelineContext, SessionState
│   ├── config.py                # PipelineConfig, RouterConfig, ContextConfig
│   ├── router/                  # 模型路由策略（选羊）
│   │   ├── __init__.py
│   │   ├── base.py              # ModelRouter ABC
│   │   ├── off.py
│   │   ├── rules.py
│   │   ├── vector.py            # 企业版
│   │   └── llm.py               # 企业版
│   ├── selector/                # 账号调度策略（薅羊毛）
│   │   ├── __init__.py
│   │   ├── base.py              # AccountSelector ABC
│   │   ├── free_first.py
│   │   ├── cost_first.py        # 企业版
│   │   ├── sticky.py
│   │   └── failover.py          # 企业版
│   ├── context_manager/         # 上下文管理策略
│   │   ├── __init__.py
│   │   ├── base.py              # ContextManager ABC
│   │   ├── passthrough.py
│   │   ├── window.py
│   │   └── summary.py           # 企业版
│   └── executor.py              # 统一执行层（流式/非流式/重试/记账/日志）
├── services/                    ← 现有，逐步迁移
│   ├── router.py                # 保留 AccountRouter，内部委托给 pipeline
│   ├── llm_client.py            # 不变
│   ├── balance.py               # 不变
│   └── scheduler.py             # 不变
├── models/
│   └── database.py              # 扩展字段 + 新表
└── routes/
    └── api.py                   # 简化为：构建 ctx → 调用 pipeline → 返回
```

---

## 九、迁移路径（增量重构，6 步）

> 每步独立可验证，不破坏现有功能。测试通过后再进行下一步。

### 步骤 1：建地基（数据模型 + 配置扩展）
- `SystemConfig` 新增字段（`_ensure_columns` 补列）
- `RequestLog` 新增观测字段
- 新建 `SessionState`、`ModelCatalog` 表
- **验证**：现有 11 个测试全部通过，管理界面正常

### 步骤 2：抽 PipelineContext + 配置加载
- 新建 `app/pipeline/context.py`、`app/pipeline/config.py`
- `PipelineConfig.load()` 从 SystemConfig 读取（默认值=现有行为）
- **验证**：纯新增，不影响现有逻辑

### 步骤 3：抽 AccountSelector 策略接口
- 新建 `app/pipeline/selector/`，把现有 `AccountRouter` 中的 sequential/round_robin/粘性逻辑迁移为策略类
- `AccountRouter` 保留为薄封装，内部委托给 Selector
- **验证**：行为与现有完全一致（sequential=free-first, round_robin=sticky 兼容）

### 步骤 4：统一 Executor（流式/非流式合并）
- 新建 `app/pipeline/executor.py`，把 `stream_with_failover` + `stream_account` + `non_stream_handler` 合并
- `api.py` 改为调用 `Executor.execute()`
- **验证**：流式/非流式行为一致，失败切换正常，记账日志正常

### 步骤 5：接入 ModelRouter + ContextManager（默认 off/passthrough）
- 新建 `app/pipeline/router/`、`app/pipeline/context_manager/`
- 管线串起来：api → ModelRouter(off) → AccountSelector → ContextManager(passthrough) → Executor
- 默认策略=现有行为，功能不变
- **验证**：全量回归测试，性能无退化

### 步骤 6：启用高级策略（vector/summary）+ 管理界面
- 管理界面增加路由/上下文策略配置项
- 向量路由接入阿里百炼 embedding
- 摘要功能启用
- **验证**：端到端测试，观测日志可追溯

---

## 十、观测指标

每次请求必须记录（写入 RequestLog + 结构化日志）：

| 指标 | 字段 | 用途 |
|---|---|---|
| 请求 ID | `request_id` | 全链路追踪 |
| 领域标签 | `domain_tag` | 路由效果分析 |
| 路由策略 | `router_strategy` | 策略使用率统计 |
| 调度策略 | `selector_strategy` | 策略使用率统计 |
| 上下文策略 | `context_strategy` | 策略使用率统计 |
| 切换次数 | `switch_count` | 账号稳定性/容灾效果 |
| 摘要使用 | `summary_used` | 上下文压缩率 |
| 账号 ID | `account_id` | 账号维度统计 |
| Token 消耗 | `prompt_tokens/completion_tokens` | 成本核算 |
| 响应时间 | `response_time_ms` | 性能监控 |
| 状态 | `status/error_message` | 错误分析 |
| 租户 ID | `tenant_id` | 企业版多租户隔离 |

**日志格式**（结构化 JSON）：
```json
{
  "request_id": "uuid",
  "tenant_id": null,
  "pipeline": {
    "router": {"strategy": "vector", "domain": "code", "latency_ms": 45},
    "selector": {"strategy": "free-first", "account_id": 4, "decision": "额度充足"},
    "context": {"strategy": "summary", "summary_used": true, "latency_ms": 0}
  },
  "executor": {"switch_count": 0, "tokens": {"prompt": 1200, "completion": 350}, "latency_ms": 2300, "status": "success"}
}
```

---

## 十一、风险与决策记录

| 决策 | 选择 | 理由 | 备选 |
|---|---|---|---|
| 路由策略默认 | `off` | 不改变现有行为，增量上线 | `rules` |
| embedding 方案 | 云端阿里百炼 | 免费额度 50 万 token、本机零内存、已有账号 | 本地 bge-small-zh（选装插件） |
| 会话状态存储 | SQLite（初期） | 零依赖，接口可换 Redis | 直接 Redis |
| 摘要模型 | 复用当前账号 | 不额外消耗，summary 策略企业版才启用 | 独立便宜模型 |
| 版本切换 | 数据库配置 `edition` | 无需改代码/重启，热切换 | 编译期分支 |
| 供应目录 | M1 建表不启用 | 为平台化预留，不增加当前复杂度 | 不建表 |
| 流式/非流式 | 统一 Executor | 消除重复代码，行为一致 | 保持两套 |

---

## 十二、与现有代码的映射关系

| 现有代码 | 重构后位置 | 处理方式 |
|---|---|---|
| `AccountRouter.select_account()` | `pipeline/selector/` + 管线统一筛选 | 拆分迁移 |
| `AccountRouter._infer_previous_account()` | `pipeline/selector/sticky.py` | 迁移，改用 SessionState |
| `AccountRouter._filter_available_accounts()` | `pipeline/executor.py`（管线统一） | 迁移 |
| `AccountRouter._check_quota_sufficient()` | `pipeline/executor.py` | 迁移 |
| `AccountRouter.mark_account_failed()` | `pipeline/executor.py` | 迁移 |
| `AccountRouter.deduct_quota()` | `pipeline/executor.py` | 迁移 |
| `stream_with_failover()` | `pipeline/executor.py` | 合并 |
| `stream_account()` | `pipeline/executor.py` | 合并 |
| `non_stream_handler()` | `pipeline/executor.py` | 合并 |
| `llm_client.py` | 不变 | Executor 调用 |
| `balance.py` | 不变 | api 层调用 |
| `scheduler.py` | 不变 | 增加 SessionState 清理任务 |
| `api.py` | 简化为入口 | 构建 ctx → 调用管线 → 返回 |

---

*文档结束。实施时按第九节迁移路径逐步推进，每步完成后更新本文档状态。*
