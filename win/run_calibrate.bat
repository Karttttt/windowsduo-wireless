@echo off
REM Two-pose angle calibration: writes angle_closed / angle_open into config.json.
setlocal
set "PY=%~dp0..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%PY%" -u "%~dp0calibrate.py"
pause