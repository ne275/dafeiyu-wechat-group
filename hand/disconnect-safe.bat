@echo off
REM 断开远程桌面前运行：把会话移交控制台，保持渲染活跃。
REM 自动请求管理员权限（tscon 需要）。
net session >nul 2>&1
if %errorlevel% neq 0 (
  mshta "vbscript:CreateObject(""Shell.Application"").ShellExecute(""%~f0"","""","""",""runas"",1)(close)"
  exit /b
)
tscon %SESSIONNAME% /dest:console
if %errorlevel% equ 0 (echo OK - 会话已移交控制台，现在可以关远程桌面了) else (echo tscon 失败，错误码 %errorlevel%)
pause
