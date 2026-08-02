#!/bin/bash
# 服务器部署脚本 — 拉取最新代码 + 重启
echo "📥 拉取最新代码..."
git pull origin main

echo "🔄 重建服务（up -d 才会应用端口变更，restart 不会）..."
docker compose up -d api worker

echo "✅ 部署完成！http://124.222.1.136"
