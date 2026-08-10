@echo off
chcp 65001 >nul

echo 正在关闭监控 SSH 隧道...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" | Where-Object { $_.CommandLine -match '3000:127.0.0.1:3000' } | ForEach-Object { Write-Host ('  关闭 PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
echo 监控隧道已关闭。
echo （注意：这只是关了本地的查看通道，服务器上的监控栈和钉钉告警仍在正常运行）
pause
