# 扩展契约 03：插件 SDK（最小 SDK）

> 版本：v0.6.0 · 状态：已定稿 · 代码位置：`app/extensions/sdk.py`

## 1. 目标

提供**最小可用的插件开发面**：钩子注册 + SPI 注册 + 上下文访问。不提供包管理、不提供独立进程模型——v0.6.0 的插件是**进程内 Python 模块**。

## 2. 插件形态

插件是一个普通 Python 模块（或包），在应用启动时被导入并完成注册：

```python
# my_plugin.py
from app.extensions.sdk import register_hook, register_spi, PluginContext


@register_hook("route.after", priority=50)
async def prefer_cheap(ctx: PluginContext):
    """示例：route 之后若路由成本偏高，尝试改为更便宜的候选（仅演示）"""
    # ctx 是对 PipelineContext 的受限视图，见第 4 节
    pass
```

## 3. 注册 API

| 函数 | 签名 | 说明 |
|---|---|---|
| `register_hook` | `(event: str, priority: int = 1000)` | 装饰器：注册钩子函数，`priority` 越小越先执行 |
| `register_spi` | `(spi_type: str, name: str, impl)` | 注册 SPI 实现（classifier/selector/router/context/security/adapter） |
| `get_plugin` | `(name: str) -> PluginContext` | 运行时取回自己命名空间 |

## 4. PluginContext（受限上下文视图）

插件**不直接接触 `PipelineContext`**，而是通过 `PluginContext` 访问：

```python
class PluginContext:
    ctx: PipelineContext        # 底层对象（只读访问核心字段）
    data: dict                  # 本插件专属命名空间（== ctx.extensions[plugin_name]）

    def get(self, key, default=None): ...
    def set(self, key, value): ...          # 只写自己的命名空间
    def set_decision(self, field, value): ...  # 仅 after 类钩子可用（见契约 02 第 3 节）
```

## 5. 生命周期与加载

- 插件加载入口：`app/extensions/loader.py`，启动时扫描 `WOOLGATE_PLUGINS` 环境变量（逗号分隔模块路径）逐个 import；
- 默认不加载任何插件（`WOOLGATE_PLUGINS=""`），零行为变化；
- 插件 import 失败：记日志、跳过该插件，**不影响应用启动**。

## 6. 异常与隔离

| 场景 | 行为 |
|---|---|
| 钩子抛普通异常 | 记日志并继续（不中断管线） |
| before 钩子抛 `HookBlocked` | 请求被拒绝，返回 4xx |
| SPI 实现抛异常 | 按该 SPI 的降级策略处理（如分类器异常 → fallback_model） |
| 插件 import 失败 | 跳过并告警，应用照常启动 |

## 7. 示例插件模板

完整可运行示例见 `examples/plugins/minimal_plugin.py`，包含：注册、命名空间读写、钩子、SPI 替换四个最小用例。
