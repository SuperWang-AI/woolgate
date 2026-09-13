# WoolGate 快速启动指南

从零到「客户端通过 WoolGate 用上免费模型」，大约 5 分钟。

## 前置准备

- 已安装 Docker 与 Docker Compose
- （可选）一个已注册的大模型厂商账号，用于免费向导一键接入。当前内置：DeepSeek、阿里百炼（通义）、Kimi（月之暗面）、智谱、豆包（火山方舟）、腾讯混元、百度千帆、硅基流动等。

---

## 第一步：生成加密密钥

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

复制输出（类似 `gAAAAABh...` 的长串）——这是加密存储 API Key 的密钥。

## 第二步：配置环境变量

```bash
cd woolgate
cp .env.example .env
```

编辑 `.env`：

```env
HOST=0.0.0.0
PORT=8765
DATA_PATH=./data
LOG_LEVEL=INFO

# 网关鉴权密钥（客户端接入时用的 API Key，建议强随机串）
GATEWAY_BEARER_TOKEN=你的安全密钥（随机字符串）

# 第一步生成的加密密钥
ENCRYPTION_KEY=上一步生成的加密密钥
```

## 第三步：启动服务

```bash
docker compose up -d

# 查看日志
docker compose logs -f
```

等待日志出现服务启动完成提示。

## 第四步：打开管理后台

浏览器访问 **http://localhost:8765/admin**

## 第五步：免费向导一键接入（推荐）

1. 管理后台首页 → 进入「免费向导」
2. 选择你已注册的厂商（如 DeepSeek）
3. 复制该厂商控制台的 API Key 粘贴到输入框
4. 点击「一键自动配置」

完成后会自动完成：创建账号 → 同步该厂商全部模型 → 生成能力向量 → 启用。回到「账号管理」即可看到已就绪的模型。

> 没有厂商账号？也可以先跳过，用本地模型（Ollama）或后续手动添加。

## 第六步：对接你的客户端

### Dify

1. 「设置 → 模型供应商」→ 添加 `OpenAI-API-compatible`
2. 配置：

| 配置项 | 值 |
|---|---|
| 模型名称 | `woolgate` |
| Base URL | `http://localhost:8765/v1`（或 `http://woolgate:8765/v1`，Dify 与 WoolGate 同网络时） |
| API Key | 你的 `GATEWAY_BEARER_TOKEN` |

3. 保存后在应用中选择该模型即可对话。

### OpenClaw

在 OpenClaw 配置中：

```yaml
model:
  provider: openai-compatible
  base_url: http://localhost:8765/v1
  api_key: your-gateway-bearer-token
  model: woolgate
```

### 任意 OpenAI 兼容工具

- **Base URL**: `http://<woolgate地址>:8765/v1`
- **API Key**: `GATEWAY_BEARER_TOKEN`
- **模型名**: `woolgate`（智能路由）或真实模型名（直连，如 `deepseek-chat`）

### 命令行验证

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Authorization: Bearer your-gateway-bearer-token" \
  -H "Content-Type: application/json" \
  -d '{"model": "woolgate", "messages": [{"role": "user", "content": "你好"}], "stream": true}'
```

返回 SSE 流即接入成功。

## 常见问题

**Q: 配置了但客户端报 401？**
A: 检查 `GATEWAY_BEARER_TOKEN` 是否与客户端填写的 API Key 一致。

**Q: 客户端报模型不存在？**
A: 默认用 `woolgate` 走智能路由；若指定真实模型名，请确认该模型已在「账号管理」中启用。

**Q: 免费向导提示 Key 无效？**
A: 确认复制的是 API Key 而非登录密码；部分厂商 Key 需在控制台单独创建。

**Q: 想用本地 Ollama 模型？**
A: 启动 Ollama 后，在「模型菜单」接入本地模型；容器部署时用 `host.docker.internal:11434` 访问宿主机。

**Q: 如何停止服务？**
A: `docker compose down`。数据保留在 `./data` 目录。
