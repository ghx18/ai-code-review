@echo off
chcp 65001 >nul
cd /d C:\Users\Lenovo\Desktop\ai-learning\projects\ai-code-review

echo [1/3] Pushing to Gitee...
git add .
git commit -m "update"
git push

echo.
echo [2/3] Syncing to server...
rem 丢弃服务器上 .pyc 等已追踪文件的本地改动（可再生的编译缓存，安全）
rem 否则 pull 会因本地改动被覆盖而中止
ssh tencent "cd /app/ai-code-review && git checkout -- . && git pull && docker compose up -d api worker"

echo.
echo [3/3] Done! http://124.222.1.136
pause
