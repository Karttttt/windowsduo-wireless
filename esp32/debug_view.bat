@echo off
REM Live viewer for the MPU6050 angle stream. Pass --port COMx if needed.
setlocal
set "PY=%~dp0..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%PY%" -u "%~dp0debug_view.py" %*
pause