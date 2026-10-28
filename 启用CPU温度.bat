@echo off
chcp 65001 >nul
title 启用 CPU 温度采集（LibreHardwareMonitor）
REM ============================================================
REM  一键启动 LHM 并验证 hwtriage 能否读到 CPU 温度
REM  需要管理员权限（读 CPU 温度必须 ring0）——本脚本会自动提权
REM  ★ 跨机器：不写死任何路径，自动探测 LHM 和 Python
REM ============================================================

REM ---- 自提权：非管理员则用 UAC 重新拉起自己 ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限，正在请求提权...
    powershell -NoProfile -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

REM ---- 脚本所在目录 = 项目根目录（跟着仓库走，换机器也对）----
set REPO=%~dp0
if "%REPO:~-1%"=="\" set REPO=%REPO:~0,-1%
cd /d "%REPO%"

REM ---- 自动找 Python：优先 py 启动器，其次 python ----
set PY=
where py >nul 2>&1 && set PY=py -3
if not defined PY (
    where python >nul 2>&1 && set PY=python
)
if not defined PY (
    echo [错误] 没找到 Python。请先安装 Python 3.9+ 并加入 PATH。
    echo        下载：https://www.python.org/downloads/
    pause & exit /b 1
)

REM ---- 自动找 LHM：问 hwtriage 自己（跨机器统一逻辑）----
echo [0/3] 探测 LibreHardwareMonitor ...
for /f "delims=" %%i in ('%PY% -c "from hwtriage.paths import find_lhm;print(find_lhm())" 2^>nul') do set LHM=%%i

if not defined LHM (
    echo.
    echo   [没找到 LibreHardwareMonitor]
    %PY% -c "from hwtriage.paths import lhm_hint;print(lhm_hint())"
    echo.
    echo   装好后重跑本脚本即可，或设置环境变量 HWTRIAGE_LHM_PATH 指向解压目录。
    pause & exit /b 1
)
echo   找到: %LHM%

echo.
echo [1/3] 启动 LibreHardwareMonitor ...
start "" "%LHM%"
echo     等待 LHM 注册 WMI 命名空间（首次约 8 秒）...
timeout /t 8 /nobreak >nul

echo.
echo [2/3] 检查 WMI 命名空间 root/LibreHardwareMonitor ...
powershell -NoProfile -Command "try { $n=(Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor -ErrorAction Stop | Where-Object {$_.SensorType -eq 'Temperature'} | Measure-Object).Count; Write-Host ('    找到温度传感器 ' + $n + ' 个') } catch { Write-Host '    命名空间还没有 —— 请在 LHM 窗口点 Options 菜单 → 勾选 WMI Provider，然后重跑本脚本' -ForegroundColor Yellow }"

echo.
echo [3/3] 用 hwtriage 实测 CPU 温度 ...
%PY% -m hwtriage --only thermal

echo.
echo 完成。若上面 CPU 温度仍是 [不可读]，就在 LHM 里勾 Options → WMI Provider 再跑一次。
echo 之后 hwtriage 会自动接管，无需改任何代码。
pause
