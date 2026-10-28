@echo off
chcp 65001 >nul
title 安装 hwtriage 每日定时巡检
REM 建一个每天 12:00 静默巡检的计划任务（无异常不写日志内容）
REM ★ 跨机器：路径全部相对本脚本自动推导

REM ---- 脚本所在目录 = 项目根目录 ----
set REPO=%~dp0
if "%REPO:~-1%"=="\" set REPO=%REPO:~0,-1%

REM ---- 自动找 Python ----
set PY=
where py >nul 2>&1 && set PY=py -3
if not defined PY (
    where python >nul 2>&1 && set PY=python
)
if not defined PY (
    echo [错误] 没找到 Python。请先安装 Python 3.9+ 并加入 PATH。
    pause & exit /b 1
)

echo 将创建计划任务「hwtriage每日巡检」，每天 12:00 运行 --cron 静默模式。
echo 项目目录：%REPO%
echo 日志：%REPO%\_cron.log
echo.

schtasks /Create /TN "hwtriage每日巡检" /SC DAILY /ST 12:00 ^
  /TR "cmd /c cd /d \"%REPO%\" && %PY% -m hwtriage --cron >> _cron.log 2>&1" /F

if %errorlevel%==0 (
    echo.
    echo [成功] 已创建。可随时用以下命令删除：
    echo   schtasks /Delete /TN "hwtriage每日巡检" /F
) else (
    echo.
    echo [失败] 创建计划任务失败，可能需要管理员权限。右键本文件「以管理员身份运行」重试。
)
pause
