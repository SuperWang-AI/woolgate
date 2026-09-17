## WoolGate v0.6.0 · 组件化 / 插件化基础设施

开源后第一个架构级版本：把核心流水线从「写死的代码」升级为「可插拔工位」，为社区插件与企业版扩展打好地基。

### ✨ 新特性

**组件化核心**
- **A1 统一上下文对象 PipelineContext**：全流水线共享稳定上下文契约（to_log_dict），日志与审计口径统一
- **A2 9 个生命周期插口 hooks**：before 可阻断请求、after 可观测，覆盖请求全链路
- **A3 插件 SDK + 加载器**：register_hook / spi 注册机制，PluginContext 白名单沙箱，启动自动加载
- **A4/A5 分类引擎组件化 + 降级链**：智能分类故障自动降级走 fallback，保障网关可用性
- **A6 租户会话隔离**：session_id 前缀隔离 + SessionStateStore SPI
- **A7 客户端适配器 SPI**：默认 OpenAI 兼容适配，可扩展非 OpenAI 协议客户端
- **A8 安全审核插口**：内置安全审核扩展点（默认放行），企业版可挂载内容审核

**路由与可观测**
- **B1 结构化日志**：log_event / ctx_event 统一事件日志
- **B2 厂商健康度滑动窗口统计**：为智能路由提供实时健康数据
- **B3 路由决策三分支重构**：免费优先 / 成本优先 / 兜底决策链 + ctx.account 修复
- **B4 扩展契约文档 6 篇** + 示例插件 + 架构/贡献/变更文档

**工程质量**
- 新增 tests/test_extensions.py（13 用例），全量 **123 passed**
- 修复 CI：GHCR 镜像名、tag 触发、测试环境，全量回归通过

### 📦 快速开始

```bash
git clone https://github.com/SuperWang-AI/woolgate.git
cd woolgate
cp .env.example .env   # 生成 ENCRYPTION_KEY 与 GATEWAY_BEARER_TOKEN
docker compose up -d   # 30 秒部署
```

打开 Web 后台（默认 8765 端口）→ 免费向导 → 粘贴 API Key 一键接入 15 家免费大模型厂商。

### 🔌 面向插件开发者

- 扩展文档：docs/extensions/（01-06）
- 示例插件：examples/ 目录
- 贡献指南：CONTRIBUTING.md

Apache-2.0 · 数据全部本地化，无任何遥测
