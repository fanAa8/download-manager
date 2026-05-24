@echo off
REM ============================================================
REM  下载分类管家 — 安装脚本
REM  双击运行即可，无需 Python 环境
REM ============================================================

echo.
echo ============================================================
echo   下载分类管家 v1.1  —  安装脚本
echo ============================================================
echo.

REM --- 1. 检查是否已存在 exe ---
set EXE=下载分类管家.exe
if not exist "%~dp0%EXE%" (
    echo [ERROR] %EXE% 未找到！
    echo         请确保此 bat 与 exe 在同一文件夹内。
    pause & exit /b 1
)

REM --- 2. 写入注册表，实现"右键 → 发送到 → 下载分类管家" ---
set KEY=HKCU\Software\Classes\Applications\%EXE%\shell\open\command
reg add "%KEY%" /ve /d "\"%~dp0%EXE%\" \"%%1\"" /f >nul 2>&1

echo [OK] 右键菜单关联完成

REM --- 3. 询问是否开机自启 ---
echo.
set /p AUTO=是否添加到开机自启动？(Y/N，默认Y):
if "%AUTO%"=="" set AUTO=Y
if /i "%AUTO%"=="Y" (
    set SCF=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\下载分类管家.lnk
    powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SCF%');$s.TargetPath='%~dp0%EXE%';$s.WorkingDirectory='%~dp0';$s.Save()"
    echo [OK] 已添加到开机自启动
) else (
    echo [跳过] 未添加自启动
)

REM --- 4. 首次运行：生成 config.json（如果不存在）---
if not exist "%~dp0config.json" (
    echo [INFO] 首次运行，正在生成默认配置...
    "%~dp0%EXE%" --init >nul 2>&1
    echo [OK] 配置已生成：%~dp0config.json
    echo       可编辑 config.json 自定义分类规则
)

echo.
echo ============================================================
echo   安装完成！
echo.
echo   使用方法：
echo     1. 双击「%EXE%」启动监控
echo     2. 编辑 config.json 修改监控目录 / 分类规则
echo     3. 查看 download_manager.log 查看运行日志
echo.
echo   卸载：删除本文件夹即可（绿色软件，无残留）
echo ============================================================
echo.
pause
