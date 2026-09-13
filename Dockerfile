FROM python:3.11-slim

WORKDIR /app

# 安装依赖（构建时可传 --build-arg PIP_INDEX_URL 使用国内镜像加速，默认官方源）
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i "$PIP_INDEX_URL"

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 暴露端口
EXPOSE 8765

# 启动命令
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765"]
