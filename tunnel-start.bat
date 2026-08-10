@echo off
chcp 65001 >nul
cd /d %~dp0

echo [1/2] 开启监控 SSH 隧道（后台运行，不占用终端）...
ssh -f -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 tencent
if errorlevel 1 (
  echo.
  echo   开启失败！检查：
  echo   1. 服务器是否在线
  echo   2. ssh 别名 tencent 是否已配置（%~dp0..\..\.ssh\config）
  pause
  exit /b 1
)

echo [2/2] 打开 Grafana 面板...
timeout /t 2 /nobreak >nul
start http://localhost:3000

echo.
echo   隧道已开启。可访问：
echo     Grafana:      http://localhost:3000   账号 admin / admin123
echo     Prometheus:   http://localhost:9090
echo     Alertmanager: http://localhost:9093
echo.
echo   用完关闭：双击 tunnel-stop.bat（监控栈本身一直在服务器上跑）
pause
