@echo off
REM Manual mode: no MCU needed. Up/Down = glass +/-, Right = 100%, Left = clear, Esc = quit.
setlocal
set "PY=%~dp0..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%PY%" -u "%~dp0glass_overlay.py" --manual
pause