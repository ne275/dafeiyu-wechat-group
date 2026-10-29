@echo off
REM disconnect-safe: hand this session to the console before closing RDP.
REM Must run as Administrator (right-click -> Run as administrator if this says NO).
fltmc >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Not administrator. Right-click this file -^> Run as administrator.
  pause
  exit /b 1
)
tscon %SESSIONNAME% /dest:console
if %errorlevel% equ 0 (
  echo [OK] Session moved to console. You may close the RDP window now.
) else (
  echo [FAIL] tscon error %errorlevel%
)
pause
