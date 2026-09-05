# WoolGate 快速启动指南

## 第一步：生成加密密钥

```bash
cd ~/.openclaw/workspace/woolgate
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

复制输出的密钥（类似：`gAAAAABh...`）

## 第二步：配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下内容：

```env
HOST=0.0.0.0
PORT=8765
DATA_PATH=./data
LOG_LEVEL=INFO
GATEWAY_BEARER_TOKEN=你的安全密钥（随机字符串）
ENCRYPTION_KEY=上一步生成的加密密钥
```

## 第三步：启动服务

### 方式A：Docker部署（推荐）

```bash
docker-compose up -d
```

### 方式B：本地运行

```bash
# 安装依赖
pip3 install -r requirements.txt

# 启动服务
python3 start.py
```

## 第四步：访问服务

- **API接口**: http://localhost:8765
- **API文档**: http://localhost:8765/docs
- **健康检查**: http://localhost:8765/health

## 第五步：添加第一个账号

使用管理界面或直接调用API添加账号。

### 示例：添加DeepSeek账号

```python
import requests

url = "http://localhost:8765/v1/chat/completions"
headers = {
    "Authorization": "Bearer 你的GATEWAY_BEARER_TOKEN",
    "Content-Type": "application/json"
}

# 首先需要通过管理界面或数据库添加账号
```

## 第六步：测试调用

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Authorization: Bearer 你的GATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

## 与Dify对接

在Dify中添加模型提供商：

1. 进入 Dify → 设置 → 模型提供商
2. 添加自定义模型
3. 填写：
   - **服务器URL**: `http://woolgate:8765/v1`
   - **API Key**: 你的 `GATEWAY_BEARER_TOKEN`
   - **模型名称**: `deepseek-v4-flash`（或其他已配置的模型）

## 与OpenClaw对接

编辑OpenClaw配置：

```yaml
models:
  - provider: openai
    base_url: http://localhost:8765/v1
    api_key: 你的GATEWAY_BEARER_TOKEN
    model: deepseek-v4-flash
```

## 常用命令

```bash
# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 进入容器
docker exec -it woolgate /bin/bash

# 运行测试
pytest tests/ -v
```

## 故障排查

### 问题1：加密密钥错误

```
ValueError: 加密密钥未配置
```

**解决**：确保在 `.env` 中设置了 `ENCRYPTION_KEY`

### 问题2：数据库锁定

```
sqlite3.OperationalError: database is locked
```

**解决**：检查是否有多个进程同时访问数据库，重启服务

### 问题3：Ollama连接失败

```
httpx.ConnectError
```

**解决**：
- 确保Ollama在宿主机运行
- Docker环境使用 `host.docker.internal:11434`
- 本地环境使用 `localhost:11434`

## 下一步

- 📖 阅读完整文档：`README.md`
- 🔧 配置更多账号
- 📊 查看统计数据
- 🧪 运行单元测试

---

**开始薅羊毛吧！🐑💰**
