@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   下载分类管家  安装
echo ============================================================
echo.

if not exist "%~dp0下载分类管家.exe" (
    echo [错误] 没有找到 下载分类管家.exe
    echo        请把本脚本和 exe 放在同一个文件夹。
    pause
    exit /b 1
)

if not exist "%~dp0config.json" (
    if exist "%~dp0config.default.json" (
        copy /Y "%~dp0config.default.json" "%~dp0config.json" >nul
        echo [完成] 已根据默认模板生成 config.json
    )
)

echo.
set /p AUTO=是否开机自动启动？^(Y/N，默认 N^): 
if /I "%AUTO%"=="Y" (
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v DownloadClassifierManager /t REG_SZ /d "\"%~dp0下载分类管家.exe\"" /f >nul
    if errorlevel 1 (
        echo [失败] 没能写入启动项，可以稍后在设置里再打开。
    ) else (
        echo [完成] 已写入当前用户的启动项。
    )
) else (
    echo [跳过] 开机启动
)

echo.
set /p SEND=是否加入“发送到”菜单？^(Y/N，默认 N^): 
if /I "%SEND%"=="Y" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('SendTo') + '\下载分类管家.lnk'); $s.TargetPath='%~dp0下载分类管家.exe'; $s.WorkingDirectory='%~dp0'; $s.Save()"
    echo [完成] 右键文件后可以“发送到 - 下载分类管家”。
) else (
    echo [跳过] 发送到
)

echo.
echo 接下来：
echo   1. 双击 下载分类管家.exe
echo   2. 左键托盘图标，或右键菜单里的“打开设置”
echo   3. 选择监控目录和整理目标
echo.
echo 卸载：先在设置里关闭开机启动，再删除“发送到”快捷方式和本文件夹。
echo 日志在同目录的 download_manager.log
echo.
pause
endlocal
