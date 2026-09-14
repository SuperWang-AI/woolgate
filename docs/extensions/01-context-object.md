# 扩展契约 01：统一上下文对象（PipelineContext）

> 版本：v0.6.0 · 状态：已定稿 · 代码位置：`app/pipeline/context.py`

## 1. 定位

`PipelineContext` 是贯穿整条请求管线（分类 → 路由 → 选号 → 上下文 → 执行）的唯一数据对象。

- **每个工位只读写自己的字段**，不直接修改其他工位的字段；
- **插件通过 `ctx.extensions` 命名空间传递自有数据**，不允许往核心字段塞私有数据；
- **日志/计费/健康度全部从本对象导出**（`to_log_dict()`），不另起数据通路。

## 2. 字段分组（按责任划分）

| 分组 | 字段 | 写入方 | 说明 |
|---|---|---|---|
| 输入 | `request_id` `client_ip` `stream` `original_messages` `requested_model` `kwargs` `estimated_tokens` `session_id` | api 层 | 只读 |
| 密钥 | `api_key_id` `default_model` `forced_model` `user_override_model` | api 层 | `user_override_model` = 请求头 `X-Model-Preference`（v0.6.0 新增） |
| 分类 | `classify_engine` `classify_decision` | 分类器 | v0.6.0 新增：记录本次分类引擎与结论 |
| 路由 | `target_model` `router_strategy` `router_decision` `router_latency_ms` `router_confidence` `model_switched` `current_model` | 路由工位 | — |
| 选号 | `account` `selector_strategy` `selector_decision` `tried_account_ids` `switch_count` | 选号工位 | — |
| 上下文 | `assembled_messages` `context_strategy` `summary_used` `context_latency_ms` | 上下文工位 | — |
| 执行 | `prompt_tokens` `completion_tokens` `response_time_ms` `status` `error_message` | 执行工位 | — |
| 成本 | `estimated_cost` `actual_cost` | 执行工位 | v0.6.0 新增：估算/实际金额（元），供省钱看板 |
| 治理 | `tenant_id` | 认证层 | 企业版；单租户为 `None` |
| 降级 | `degraded` `degrade_reason` | 执行层 | v0.6.0 新增：本次请求是否发生降级及原因 |
| 插件 | `extensions` | 插件 | v0.6.0 新增：命名空间字典，见下 |
| 阶段 | `stage` `stage_timings_ms` | 执行层 | v0.6.0 新增：当前阶段与各阶段耗时 |

## 3. 插件命名空间 `extensions`

```python
ctx.extensions: Dict[str, Any]
```

- **key = 插件注册名**（全局唯一，见 02-hooks-spi.md 的注册规则）；
- 不同插件之间**不得读取/修改彼此的命名空间**；
- 命名空间内数据**不落库**（如需持久化，由插件自行管理存储）。

## 4. 阶段标记

```python
ctx.stage: str            # 当前阶段，取值见下方常量
ctx.stage_timings_ms: Dict[str, int]  # {stage: 耗时ms}
```

阶段常量（`app/pipeline/context.py` 导出 `Stage` 类）：

```python
class Stage:
    REQUEST   = "request"
    CLASSIFY  = "classify"
    ROUTE     = "route"
    SELECT    = "select"
    CONTEXT   = "context"
    EXECUTE   = "execute"
    RESPONSE  = "response"
```

## 5. 序列化契约 `to_log_dict()`

所有结构化日志（RequestLog / 指标）必须只通过 `to_log_dict()` 导出，字段为稳定契约：

```json
{
  "request_id": "...",
  "tenant_id": null,
  "target_model": "qwen-plus",
  "router_strategy": "vector",
  "router_decision": "...",
  "router_latency_ms": 120,
  "selector_strategy": "cost-first",
  "selector_decision": "...",
  "account_id": 3,
  "switch_count": 0,
  "context_strategy": "window",
  "summary_used": false,
  "prompt_tokens": 100,
  "completion_tokens": 50,
  "response_time_ms": 800,
  "status": "success",
  "error_message": null,
  "classify_engine": "embedding",
  "degraded": false,
  "degrade_reason": "",
  "estimated_cost": 0.0012,
  "actual_cost": 0.0011
}
```

> 新增字段向后兼容：旧消费方按字段缺失容错，不要求一次性全量消费。

## 6. 会话状态（SessionState）与租户隔离

- `SessionState` 以 `session_id` 为主键；**多租户下 session_id 必须带租户前缀**：
  `{tenant_id}:{session_id}`（`tenant_id` 为空时保持原样，单租户行为不变）；
- 上下文压缩/滞回判定只允许访问**同租户**的会话状态（v0.6.0 起按前缀约束，见 06-tenant-isolation.md）。
