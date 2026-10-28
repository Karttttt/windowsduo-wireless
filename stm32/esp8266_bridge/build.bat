@echo off
REM Build the ESP8266 WiFi bridge firmware.
REM Usage: build.bat [env]     env = nodemcu (default) or esp01
setlocal
set "ENV=%~1"
if "%ENV%"=="" set "ENV=nodemcu"
for %%I in ("%~dp0..\..\..") do set "ROOT=%%~fI"
if not exist "C:\duo\WindowsDuo\." (
    mklink /J C:\duo "%ROOT%" >nul 2>&1
)
if not exist "C:\duo\WindowsDuo\." (
    echo [ERROR] cannot create junction C:\duo -^> %ROOT%
    pause
    exit /b 1
)
set "TMP=C:\duo\Temp"
set "TEMP=C:\duo\Temp"
if not exist "%TMP%" mkdir "%TMP%"
set "PLATFORMIO_CORE_DIR=C:\duo\.platformio"
set "PYTHONIOENCODING=utf-8"
set "PIO=%ROOT%\.pio-venv\Scripts\python.exe"
if not exist "%PIO%" set "PIO=python"
chcp 65001 >nul
cd /d "C:\duo\WindowsDuo\stm32\esp8266_bridge"
echo Building env: %ENV%
"%PIO%" -m platformio run -e %ENV%
pause