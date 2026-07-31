# ---- Stage 1: 依赖安装 ----
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# 国内网络环境使用清华 PyPI 镜像（直接访问 pypi.org 常因 SSL 被掐断而失败）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt


# ---- Stage 2: 运行镜像 ----
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 环境变量
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# FastAPI 端口（含 REST API + WebSocket + MCP SSE 挂载）
EXPOSE 8000

# 默认启动 FastAPI
ENTRYPOINT ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
