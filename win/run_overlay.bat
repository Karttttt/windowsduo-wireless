@echo off
REM Duo glass overlay - driven by the hinge angle from STM32/ESP32 (CH340 auto-detected).
REM Starts in AUTO mode: the glass follows the sensor right away.
REM Keys (the overlay window takes the keyboard focus itself):
REM   Up/Down = glass +/-, Left = clear, Right = 100%, r = toggle auto, Esc = quit
setlocal
set "PY=%~dp0..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
"%PY%" -u "%~dp0glass_overlay.py" --auto %*
pause