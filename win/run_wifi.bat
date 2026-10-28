@echo off
REM Duo glass overlay over WiFi - reads the JSON stream from the ESP8266 bridge.
REM
REM Usage:
REM   run_wifi.bat                       auto-discover the bridge on the current /24
REM   run_wifi.bat 10.234.186.114:8266   explicit address (skips discovery)
REM   run_wifi.bat --duration=30         extra flags are passed through
setlocal
set "PY=%~dp0..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
set "ARG=%~1"
if "%ARG%"=="" goto auto
if "%ARG:~0,2%"=="--" goto auto
"%PY%" -u "%~dp0glass_overlay.py" --auto --tcp=%ARG%
goto done
:auto
"%PY%" -u "%~dp0glass_overlay.py" --auto --tcp %*
:done
pause