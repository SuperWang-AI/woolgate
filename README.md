# WoolGate 🐑

**LLM多账号免费额度智能调度网关**

一个专为内网自用设计的LLM网关，智能调度多个账号的免费额度，最大化薅各厂商羊毛，并统计薅取价值。

## 核心特性

- 🎯 **智能调度**：优先级排序 + 顺序/轮询双策略
- 💰 **羊毛价值统计**：基于市场行情价实时计算薅取价值
- 🔄 **双配额体系**：Token配额 / 金额配额灵活支持
- 🛡️ **流式安全保护**：SSE出流后禁止换账号，杜绝上下文割裂
- ⚡ **额度预判**：请求前预判剩余额度，避免中途耗尽
- 🔁 **智能重试**：指数退避+随机抖动，防止雪崩
- 📊 **完整统计**：每日/累计羊毛价值、Token消耗趋势
- 🖥️ **Web管理界面**：基于NiceGUI的完整管理面板
- 🐳 **Docker部署**：开箱即用，与Dify、OpenClaw无缝对接

## 快速开始

### 1. 生成加密密钥

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入配置：

```bash
cp .env.example .env
```

编辑 `.env`：
```env
HOST=0.0.0.0
PORT=8765
GATEWAY_BEARER_TOKEN=your-secret-token-here
ENCRYPTION_KEY=你生成的加密密钥
```

### 3. Docker部署

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 4. 访问服务

- **API接口**: http://localhost:8765
- **API文档**: http://localhost:8765/docs
- **管理界面**: http://localhost:8766

## 对接上游

### Dify配置

在Dify中添加自定义模型：

- **服务器URL**: `http://woolgate:8765/v1`
- **API Key**: 填入你的 `GATEWAY_BEARER_TOKEN`
- **模型名称**: 在WoolGate中配置的模型ID

### OpenClaw配置

在OpenClaw的模型配置中：

```yaml
models:
  - provider: openai
    base_url: http://woolgate:8765/v1
    api_key: your-gateway-bearer-token
    model: deepseek-v4-flash
```

## 管理界面使用

### 账号管理

1. 点击"新增账号"
2. 填写厂商、模型ID、API Key
3. 设置优先级（数值越大越优先）
4. 配置配额类型和市场价格
5. 保存并启用

### 系统配置

- **额度耗尽策略**：自动切换/返回错误/允许付费
- **重试配置**：最大重试次数、冷却时间
- **Ollama配置**：启用/禁用、地址设置
- **日志配置**：自动清理天数

### 统计仪表盘

- 累计/今日薅羊毛价值
- 账号状态和额度使用情况
- 请求日志和Token消耗

## 路由策略

### 顺序耗尽（sequential）

按优先级排序，高优先级账号先薅，用完再下一个。适合批量养号场景。

### 轮询（round_robin）

忽略优先级，账号轮流使用，防止单账号限流。

## Ollama支持

WoolGate对Ollama提供特殊支持：

- 跳过额度检查和扣费
- 羊毛价值归零（本地模型无成本）
- 自动检测运行状态

## 双计价体系

### 厂商配额计价（调度用）

用于判断额度是否够用、扣费、每日重置：
- Token模式：直接统计Token数
- 金额模式：按厂商内部单价换算

### 市场行情计价（统计用）

用于计算薅羊毛价值：
- 统一采用公开市场标准价
- 可手动自定义价格
- 支持历史数据重算

## API接口

### 聊天补全

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

### 列出模型

```bash
curl http://localhost:8765/v1/models \
  -H "Authorization: Bearer your-token"
```

## 企业版

开源版面向个人与自用场景，免费聚合各厂商免费额度并智能调度。**团队与组织**需要以下能力时可升级企业版：

- **多租户**：团队/项目隔离，独立 Key 与权限
- **配额预算**：按租户统计用量，超限自动停用
- **审计与账单**：按租户隔离日志与费用明细
- **本地智能省钱模式**：本地 embedding + 本地判题 + 本地简单直答，数据不出域

企业版在开源版中已预留升级入口，计划即将推出；如需提前接入，请通过项目主页联系作者。

## 安全说明

⚠️ **本项目仅供内网自用**

- 不做灰产：无自动注册、无接码、无批量养号
- 仅手动导入已有实名账号
- 不暴露公网
- API Key加密存储

## 技术栈

- **后端**: FastAPI + Uvicorn
- **数据库**: SQLite + SQLAlchemy (异步)
- **协议适配**: LiteLLM SDK
- **加密**: Cryptography (Fernet)
- **定时任务**: APScheduler
- **管理界面**: NiceGUI
- **部署**: Docker + Docker Compose

## 项目结构

```
woolgate/
├── app/
│   ├── models/          # 数据库模型
│   ├── routes/          # API路由
│   ├── services/        # 业务逻辑（路由、LLM客户端、定时任务）
│   ├── utils/           # 工具函数（加密）
│   ├── ui/              # NiceGUI管理界面
│   └── config.py        # 配置管理
├── data/                # 数据库存储
├── logs/                # 日志文件
├── tests/               # 单元测试
├── main.py              # 主应用入口
├── requirements.txt     # Python依赖
├── Dockerfile           # Docker镜像
├── docker-compose.yml   # Docker编排
└── .env.example         # 环境变量示例
```

## 开发调试

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py
```

### 运行测试

```bash
pytest tests/
```

## 常见问题

### Q: 如何重置每日额度？

A: 系统每天凌晨00:00自动重置daily类型账号的额度。

### Q: 如何手动清理日志？

A: 系统每天凌晨03:00自动清理过期日志，也可以在数据库中手动删除。

### Q: Ollama无法连接？

A: 确保Docker容器能访问宿主机，使用 `host.docker.internal:11434`。

### Q: 流式响应中断怎么办？

A: 检查账号额度是否充足，查看请求日志中的错误信息。

## 许可证

MIT License

---

**薅羊毛，有智慧！🐑💰**
