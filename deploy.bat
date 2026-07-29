@echo off
chcp 65001 >nul
cd /d C:\Users\Lenovo\Desktop\ai-learning\projects\ai-code-review

echo [1/3] Pushing to Gitee...
git add .
git commit -m "update"
git push

echo.
echo [2/3] Syncing to server...
ssh -i %USERPROFILE%\.ssh\id_ed25519 ubuntu@124.222.1.136 "cd /app/ai-code-review && git pull && docker compose restart api worker"

echo.
echo [3/3] Done! http://124.222.1.136
pause
