# 扩展契约 04：分类引擎（Classifier）组件化与降级

> 版本：v0.6.0 · 状态：已定稿 · 代码位置：`app/extensions/classifiers.py`

## 1. 问题

v0.5.0 中"智能分类"（判断用户请求该走哪个模型）与"向量/LLM 路由"耦合在 `VectorRouter` / `LLMRouter` 内，替换分类手段（如改用免费小模型、本地模型）必须改代码。

## 2. 组件化后的形态

```python
class Classifier(ABC):
    """分类引擎 SPI：输入用户请求，输出目标模型与置信度"""

    name: str                       # "vector" / "llm" / "local"
    @abstractmethod
    async def classify(self, ctx) -> ClassificationResult: ...
```

```python
@dataclass
class ClassificationResult:
    model: str            # 推荐的目标模型名
    confidence: float     # 置信度 0~1
    engine: str           # 实际使用的引擎名
    decision: str         # 人类可读决策说明
    latency_ms: int
```

内置实现：

| 实现 | 说明 |
|---|---|
| `VectorClassifier` | 现有向量路由逻辑（embedding 相似度 + 滞回） |
| `LLMClassifier` | 现有 LLM 路由逻辑（小模型推荐 + 理由） |
| `LocalClassifier` | 本地模型分类（Ollama，预留；企业本地部署场景） |

## 3. 选择与组合（RouterConfig）

```python
classifier_engine: str = "auto"   # auto / vector / llm / local / hybrid
```

- `auto`（默认）：按现有 `router_strategy` 推断（vector→VectorClassifier，llm→LLMClassifier，hybrid→先 vector 低置信度升级 llm）；
- 显式指定：强制使用指定引擎（`hybrid` 与现状一致：vector 置信度 < `threshold_high` 时升级 LLM）；
- 后续可注册自定义引擎（企业行业专用分类器）。

## 4. 降级链（A5，按序尝试直到成功）

1. 主引擎异常/超时 → 记 `degraded=True`，降级到 **fallback 分类**（`RouterConfig.fallback_model` 或 `default_model`）；
2. fallback 模型无可用账号 → 交给选号工位全量候选（已有兜底逻辑不变）；
3. 全部失败 → 503（与现状一致）。

> 降级原则：**分类是辅助，可用性是底线**。分类引擎挂掉时路由退化为"默认模型直走"，绝不因为分类故障拒绝服务。

## 5. 用户覆盖（请求级）

| 途径 | 字段 | 优先级 |
|---|---|---|
| 斜杠命令 `/model` | `forced_model` | 最高 |
| 请求头 `X-Model-Preference` | `user_override_model` | 次高（v0.6.0 新增） |
| API Key 默认模型 | `default_model` | 第三 |
| 分类引擎决策 | `target_model` | 最低 |

> 覆盖语义：用户显式指定模型时**跳过智能分类**（分类仍执行但结果不生效，`router_decision` 标注 override），避免白烧一次分类调用。
