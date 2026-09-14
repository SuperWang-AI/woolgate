"""
WoolGate 扩展包（v0.6.0 组件化/插件化预留）

- hooks: 9 个生命周期插口 + 钩子注册表
- sdk: 插件 SDK（register_hook / register_spi / PluginContext）
- classifiers: 分类引擎 SPI（vector/llm/local + 工厂）
- security: 安全审核插口（默认放行）
- adapters: 客户端适配器 SPI（OpenAI 兼容默认）
- stores: 会话状态存储 SPI（租户隔离前缀）
- loader: 插件加载器（WOOLGATE_PLUGINS 环境变量）

契约文档：docs/extensions/（01~06）。
"""
from app.extensions import hooks, sdk  # noqa: F401

__all__ = ["hooks", "sdk"]
