#!/bin/bash
# 服务器部署脚本 — 拉取最新代码 + 重启
echo "📥 拉取最新代码..."
git pull origin main

echo "🔄 重启服务..."
docker compose restart api worker

echo "✅ 部署完成！http://124.222.1.136"
