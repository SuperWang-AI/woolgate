# WoolGate · AI 聚合网关

> **English**: [README.md](README.md) · **中文**: 以下正文

**WoolGate 是一个自托管开源 AI 聚合网关：把国内厂商免费大模型 API 聚合到一个 OpenAI 兼容端点，智能路由省钱，30 秒 Docker 部署，本地模型兜底。Apache-2.0。**

客户端（Dify / OpenClaw / 任何 OpenAI 兼容工具）只需配置一个地址、一个模型名，WoolGate 在背后帮你完成：免费额度调度、任务分类路由、本地模型分流、上下文管理。用户只做一次配置，剩下的交给网关。

## 为什么需要 WoolGate

日常使用大模型，钱主要浪费在三处：

1. **该用免费的用了付费的** — 闲聊、翻译、简单问答用免费模型完全够，但很多客户端只能配一个付费模型，一视同仁地烧钱。
2. **该用便宜的用了贵的** — 编程、绘图、视频这类任务模型价格差几十倍，用最贵的模型干最普通的事。
3. **付费模型干了本地模型的活** — 判题、向量化、简单直答这类高频低难度调用，本地小模型就能胜任，成本趋近于零。

WoolGate 的智能路由正是为这三类浪费而设计：**免费优先、按任务分类、成本排序、本地分流**，把每一次请求送到最经济的模型上。

## 核心特性

- **免费向导** — 内置国内主流免费模型目录（DeepSeek、通义、Kimi、智谱、豆包、混元、千帆等），复制注册账号拿到的 API Key，粘贴即自动完成「建账号 → 同步模型 → 计算能力向量 → 启用」，全程 30 秒。
- **智能路由** — 请求先做任务分类（编程 / 创意写作 / 对话 / 向量 / 通用），再按「免费优先 → 成本优先 → 兜底」逐级选择最经济的可用模型；路由判定可选用 LLM 智能驱动或向量匹配，均优先使用本地/免费模型完成。
- **统一模型名** — 客户端只配一个对外模型名（默认 `woolgate`），由网关内部路由；也可以精确指定真实模型名直连某个模型。
- **账号管理** — 厂商 → 账号（API Key）→ 模型三层结构：一个 Key 挂载该厂商全部模型，启用停用、智能同步、Key 加密存储。
- **模型菜单** — 内置模型目录（本地模型 + 免费模型 + 各厂商型号），支持筛选与一键接入。
- **上下文管理** — 窗口截断 / 摘要压缩 / 直通三种策略，长对话不爆上下文。
- **本地模型接入** — 内置 Ollama 支持，本地模型用于 embedding、任务判题与简单直答，数据不出域。
- **流式安全** — SSE 出流后锁定账号，杜绝流式响应中途切换导致上下文割裂。
- **额度预判与智能重试** — 请求前预判剩余额度避免中途耗尽；失败指数退避 + 随机抖动重试，防止雪崩。
- **Web 管理后台** — 免费向导、账号管理、模型菜单、管线策略、系统配置、日志一站式可视化管理。
- **Docker 一键部署** — 开箱即用，镜像已精简至 400MB 级。

## 快速开始

### 1. 启动服务

```bash
git clone https://github.com/SuperWang-AI/woolgate.git
cd woolgate
cp .env.example .env   # 按注释生成并填入 ENCRYPTION_KEY 与 GATEWAY_BEARER_TOKEN
docker compose up -d
```

### 2. 打开管理后台

浏览器访问 **http://localhost:8765/admin**

### 3. 免费向导一键接入

后台首页进入「免费向导」，选择你已注册的厂商（如 DeepSeek），粘贴 API Key，点击一键配置——账号、模型、能力向量全部自动完成，无需手动维护。

### 4. 对接你的客户端

在 Dify / OpenClaw / 任意 OpenAI 兼容工具中：

- **Base URL**: `http://<woolgate-地址>:8765/v1`
- **API Key**: 你的 `GATEWAY_BEARER_TOKEN`
- **模型名**: `woolgate`（智能路由）或指定真实模型名（如 `deepseek-chat`，直连）

详见 [QUICKSTART.md](QUICKSTART.md)。

## 客户端接入示例

### Dify

「设置 → 模型供应商 → OpenAI-API-compatible」新增：

| 配置项 | 值 |
|---|---|
| 模型名称 | `woolgate` |
| Base URL | `http://woolgate:8765/v1`（容器同网段时） |
| API Key | 你的 `GATEWAY_BEARER_TOKEN` |

### OpenClaw

```yaml
model:
  provider: openai-compatible
  base_url: http://woolgate:8765/v1
  api_key: your-gateway-bearer-token
  model: woolgate
```

### curl 直测

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Authorization: Bearer ${GATEWAY_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"model": "woolgate", "messages": [{"role": "user", "content": "你好"}], "stream": true}'
```

## 智能路由如何省钱（演示）

访问仓库内演示页 **`static/wg_routing_demo.html`**（浏览器直接打开），动画演示一次请求从客户端 → 网关 → 智能分类 → 路由决策 → 模型池的完整过程：怎么把对话路由到最经济的模型、怎么用本地模型分流、怎么在免费模型中选领域最匹配的那个。

## 架构总览

```
客户端 (Dify / OpenClaw / OpenAI 兼容)
        │  OpenAI 兼容协议 /v1
        ▼
┌─────────────────── WoolGate 网关 ───────────────────┐
│  API 层      /v1/chat/completions  /v1/models        │
│  管线层      任务分类 → 路由决策 → 模型选择 → 执行     │
│  路由        LLM 路由 / 向量路由 / 免费优先 / 成本优先  │
│  选择器      免费优先 · 成本优先 · 粘性 · 轮询 · 兜底   │
│  上下文      窗口 / 摘要压缩 / 直通                   │
│  扩展层      9 生命周期插口 · 插件 SDK · SPI 组件池     │
│  账号层      厂商 → 账号(Key) → 模型，加密存储         │
│  管理后台    /admin（免费向导 / 账号 / 模型菜单 / 策略）│
└──────────────────────────────────────────────────────┘
        │
        ▼
  模型池（DeepSeek / 通义 / Kimi / 智谱 / 豆包 / Ollama …）
```

> v0.6.0 起支持组件化/插件化：分类引擎、客户端适配器、会话存储、安全审核等均可通过 SPI 替换；插件通过 `WOOLGATE_PLUGINS` 环境变量加载，失败跳过不影响启动。详见 [ARCHITECTURE.md](ARCHITECTURE.md#七组件化插件化v060) 与 [docs/extensions/](docs/extensions/)。

## 项目结构

```
woolgate/
├── app/
│   ├── models/          # 数据模型（厂商 / 账号 / 模型 / 日志）
│   ├── pipeline/        # 请求管线（路由 / 选择器 / 上下文管理 / 执行器）
│   ├── extensions/      # 扩展层（hooks / SDK / SPI / 插件加载器）
│   ├── routes/          # OpenAI 兼容 API
│   ├── services/        # 业务服务（免费向导 / 模型目录 / 账号 / 余额 / 会话 / 健康度）
│   ├── ui/              # 管理后台
│   └── config.py        # 配置管理
├── docs/extensions/     # 扩展契约文档（01~06）
├── examples/plugins/    # 示例插件模板
├── static/              # 静态资源（路由演示页等）
├── tests/               # 单元测试（pytest，可 CI 回归）
├── main.py              # 主应用入口
├── requirements.txt     # Python 依赖
├── Dockerfile           # Docker 镜像
├── docker-compose.yml   # Docker 编排
└── .env.example         # 环境变量示例
```

## 管理后台

| 页面 | 说明 |
|---|---|
| 首页 | 概览、引导式接入（AI 聚合网关使用向导） |
| 免费向导 | 免费模型一键接入 |
| 账号管理 | 厂商 / 账号 / 模型三层管理与启用停用 |
| 模型菜单 | 内置模型目录与筛选 |
| 管线策略 | 路由与上下文策略配置 |
| 系统配置 | 全局配置 |
| 日志 | 请求日志与统计 |

## 企业版

开源版面向个人与自用，免费聚合各厂商额度并智能调度。**团队与组织**需要以下能力时可升级企业版：

- **多租户**：团队/项目隔离，独立 Key 与权限
- **配额预算**：按租户统计用量，超限自动停用
- **审计与账单**：按租户隔离日志与费用明细
- **本地智能省钱模式**：本地 embedding + 本地判题 + 本地简单直答，数据不出域

企业版在开源版中已预留升级入口，计划即将推出；如需提前接入，请通过项目主页联系作者。

## 安全说明

- API Key 使用 Fernet 加密存储（`ENCRYPTION_KEY`）
- 网关鉴权依赖 `GATEWAY_BEARER_TOKEN`，请设置强随机值
- 建议仅在内网使用，不要直接暴露公网
- 仅手动导入自有账号，不提供自动注册、接码等能力

## 技术栈

- **后端**: FastAPI + Uvicorn
- **数据库**: SQLite + SQLAlchemy（异步）
- **协议适配**: LiteLLM SDK
- **加密**: Cryptography (Fernet)
- **调度**: APScheduler
- **管理后台**: 自研 Web UI
- **部署**: Docker + Docker Compose

## 开发调试

```bash
pip install -r requirements.txt
python main.py          # 本地启动
pytest tests/           # 运行单元测试
```

## 常见问题

**Q: 客户端填什么模型名？**
A: 默认填 `woolgate` 走智能路由；需要固定某个模型时填该厂商真实模型名（如 `deepseek-chat`）即可直连。

**Q: 免费向导里没看到我想要的厂商？**
A: 当前内置国内主流免费模型厂商；也可以在模型菜单手动新增模型，或在账号管理中手动添加账号。

**Q: Ollama 本地模型怎么连？**
A: 确保 Ollama 已启动，Docker 部署时容器内通过 `host.docker.internal:11434` 访问宿主机。

**Q: 流式响应中断怎么办？**
A: 检查账号额度是否充足，查看后台日志中的错误信息。

## License

[Apache License 2.0](LICENSE) © 2026 SuperWang-AI
