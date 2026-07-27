@echo off
chcp 65001 >nul
cd /d C:\Users\Lenovo\Desktop\ai-learning\projects\ai-code-review

echo 📤 提交代码到 Gitee...
git add .
git commit -m "update"
git push

echo.
echo ☁️ 同步到服务器...
ssh ubuntu@124.222.1.136 "cd /app/ai-code-review && git pull && docker compose restart api worker"

echo.
echo ✅ 部署完成！http://124.222.1.136
pause
