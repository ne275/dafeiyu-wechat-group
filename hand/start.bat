@echo off
REM DaFeiYu one-click starter: double-click this file.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0watchdog.ps1"
pause
