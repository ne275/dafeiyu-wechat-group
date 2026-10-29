@echo off
REM DaFeiYu one-click starter: update all files, then run watchdog.
cd /d "%~dp0"
python "%~dp0update.py"
python "%~dp0watchdog.py"
pause
