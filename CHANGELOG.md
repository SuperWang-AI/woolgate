# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。所有重要变更都会记录在此文件。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [Unreleased]

### 待发布
- 英文 README 简介
- 镜像 CI 自动构建（GHCR）

## [0.5.0] - 2026-09-13（开源首发）

### 新增（核心能力）
- **免费向导**：内置国内主流免费模型目录（DeepSeek / 通义 / Kimi / 智谱 / 豆包 / 混元 / 千帆 / 硅基流动等），粘贴 API Key 一键完成「建账号 → 同步模型 → 能力向量 → 启用」
- **智能路由**：任务分类（编程 / 创意写作 / 对话 / 向量 / 通用）→ 免费优先 → 成本优先 → 兜底选择
- **统一对外模型名 `woolgate`**：客户端只配一个模型名，网关内部路由；也支持精确指定真实模型名直连
- **A2 启动意图引导**：首次启动 3 问（使用方式 / 主要场景 / 模型来源）自动套用推荐策略模板
- **A3 学习型路由地基**：请求日志反馈字段（user_feedback + implicit_signal）+ `POST /v1/feedback` 上报端点 + 响应头暴露 `X-Request-Id`
- **/demo 路由可视化演示页**：动画演示请求从客户端 → 网关 → 智能分类 → 路由决策 → 模型池的省钱过程

### 新增（管理后台）
- 账号管理三层结构：厂商 → 账号（API Key）→ 模型，启用停用 / 智能同步
- 模型菜单（原厂商目录）：内置模型目录、网格卡片、筛选查询、原厂图标
- 管线策略页：路由 / 选择器 / 上下文策略可视化配置
- 系统配置页：面板化统一风格
- 管理后台 SPA 化：顶部导航零整页刷新
- 全站汉化、UI 风格统一、术语定调（自动 → 智能）

### 架构与性能
- M4 LLM 智能路由重构：从配置驱动转向 LLM 智能驱动，模型能力向量 + LLM 路由兜底
- 管线抽象：Router（off/rules/vector/llm）× Selector（pin/free-first/round-robin/sticky/failover/cost-first）× ContextManager（passthrough/window/summary）
- 流式安全：SSE 出流后锁定账号，杜绝流式响应中途切换
- 会话粘性、失败重试与降级、额度预判
- Ollama 本地模型接入（embedding / 判题 / 简单直答，数据不出域）
- **镜像瘦身：883MB → 423MB（-52%）**

### 修复
- 厂商卡片选中高亮（唯一 data-vendor-id 匹配）
- 免费向导 Key 语义统一（留空沿用 / 填写更换）
- 硅基流动分组重复（命名历史脏数据归一）
- 422 content 数组兼容、kimi-k2.6 temperature 兼容
- 客户端主动断开不再误记 success（stream_interrupted）
- 确定性兜底改为按模型加入时间倒序（最近添加最优先）

### 安全
- API Key Fernet 加密存储（ENCRYPTION_KEY）
- 无默认凭据：GATEWAY_BEARER_TOKEN / ENCRYPTION_KEY 未配置拒绝启动
- 零遥测：无任何统计上报 SDK
- CI 双 job：pytest 回归 + gitleaks 密钥泄漏扫描（全历史）
- 依赖漏洞扫描清零

### 开源合规
- Apache-2.0 LICENSE（Copyright 2026 SuperWang-AI）
- README / QUICKSTART / ARCHITECTURE 文档
- CONTRIBUTING / SECURITY 指南
- 仓库清理：移除开发归档脚本与内部文档

## [0.1.0] - 2026-08-28（内部里程碑：工具可用）

### 新增
- 多账号聚合：一个 OpenAI 兼容入口调度多个厂商账号
- 虚拟模型名映射（chat → 上游真实模型名）
- 会话粘性（消息历史复用账号）
- 账号管理增删改查
- 流式失败自动切换账号
- Ollama 本地大模型接入
- 统一余额逻辑（厂商余额 + 每日同步 + 用量统计）
- 管理后台 4 页 tab 结构

[Unreleased]: https://github.com/SuperWang-AI/woolgate/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/SuperWang-AI/woolgate/releases/tag/v0.5.0
[0.1.0]: https://github.com/SuperWang-AI/woolgate/commits/v0.5.0
