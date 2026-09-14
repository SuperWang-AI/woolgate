# 扩展契约 02：生命周期插口与 SPI

> 版本：v0.6.0 · 状态：已定稿 · 代码位置：`app/extensions/hooks.py`、`app/extensions/sdk.py`

## 1. 设计心智模型

**层是虚拟标签，工位是真实类，插口是代码里的挂载点。**

- 四工位 = 分类（classify）→ 路由（route）→ 选号（select）→ 上下文（context）→ 执行（execute）；
- 每个工位前后各有一个**插口（hook）**，加上请求开始/结束与异常，共 **9 个插口**；
- 插口只负责"在正确的时机调你"，**不关心你是什么**——这就是组件化/插件化的基础。

## 2. 插口清单（9 个）

| # | 插口名 | 时机 | 典型用途 |
|---|---|---|---|
| 1 | `request.started` | 请求进入管线、尚未做任何决策 | 审计、租户注入、限流 |
| 2 | `classify.after` | 分类引擎给出结果后 | 覆盖分类结果、注入用户偏好 |
| 3 | `route.before` | 路由决策前 | 强制指定模型（企业策略） |
| 4 | `route.after` | 路由决策后 | 校验/修正目标模型 |
| 5 | `select.after` | 选定账号后 | 审批、配额检查、账号白名单 |
| 6 | `context.after` | 消息组装完成后 | 内容改写、脱敏、注入系统提示 |
| 7 | `execute.after` | 上游调用成功后 | 缓存响应、质量评分 |
| 8 | `request.finished` | 请求结束（成功或失败） | 计费、指标、日志增强 |
| 9 | `error.occurred` | 管线任意阶段抛异常 | 告警、降级、重试策略 |

> 插口语义统一为 `before` / `after` / `error` 三种时机；before 可阻断（抛异常即拒绝），after 只可观测或改写 `extensions`，不可改核心决策字段（防止插件破坏管线）。

## 3. 钩子注册与优先级

```python
from app.extensions.sdk import register_hook

@register_hook("route.before", priority=100)
async def enforce_whitelist(ctx):
    """优先级数值越小越先执行；同优先级按注册顺序"""
    ...
```

- **priority 规则**：数值**越小越先执行**（默认 1000）；同优先级按注册先后；
- **异常隔离**：单个钩子抛异常不拖垮管线——默认吞掉并记日志（`hook.error` 除外，它决定降级）；
- **短路**：`before` 类钩子抛 `HookBlocked` 异常可主动拒绝请求（如安全审核拦截）。

## 4. SPI（Service Provider Interface）

SPI 是可被**替换实现**的接口，插件通过注册自定义实现覆盖内置行为：

| SPI | 接口 | 内置实现 | 可替换点 |
|---|---|---|---|
| 分类引擎 | `Classifier` | `VectorClassifier` / `LLMClassifier` / `LocalClassifier` | 用便宜/免费模型替代 embedding 做意图分类 |
| 账号选择 | `AccountSelector` | pin/free-first/round-robin/sticky/failover/cost-first | 企业自定义调度策略 |
| 路由策略 | `ModelRouter` | off/vector/llm/hybrid | 企业行业专用路由 |
| 上下文管理 | `ContextManager` | passthrough/window/summary | 企业级摘要/脱敏 |
| 安全审核 | `SecurityGuard` | `NoopSecurityGuard`（默认放行） | 入站/出站内容审核（企业池） |
| 客户端适配 | `ClientAdapter` | `OpenAICompatAdapter` | 接入非 OpenAI 兼容客户端 |

SPI 实现通过 `app/extensions/sdk.py` 的注册表挂载（详见 03-plugin-sdk.md）。

## 5. 安全审核插口（A8 契约）

安全能力以 **SPI + 插口** 双通道预留，开源版默认放行，企业版注入实现：

```python
class SecurityGuard(ABC):
    """安全审核守卫：入站内容过滤 + 出站内容审计"""

    @abstractmethod
    async def check_input(self, ctx, messages) -> None:
        """入站审核：违规/敏感内容 → raise SecurityBlocked 拒绝；可脱敏（改写 messages）"""

    @abstractmethod
    async def check_output(self, ctx, response) -> None:
        """出站审计：响应内容合规检查；可脱敏（改写 response）"""
```

- 触发时机：`classify.before`（入站）与 `execute.after`（出站）之前；
- 开源版默认 `NoopSecurityGuard`（无成本、零拦截）；
- 企业版可注册私有实现：敏感信息脱敏、Prompt Injection 防护、部门级内容策略。

## 6. 钩子与插口在管线中的精确位置

```
request.started
  └→ classify ──→ classify.after
        └→ route.before → route ──→ route.after
              └→ select ──→ select.after
                    └→ context ──→ context.after
                          └→ execute ──→ execute.after
                                └→ request.finished
      任意阶段异常 ──→ error.occurred
```

> 实现说明：钩子调用点集中在 `app/pipeline/executor.py` 的 `execute()` 与各工位边界；无插件注册时整条链零开销（registry 为空直接返回）。
