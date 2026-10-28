@echo off
REM Flash the ESP8266 bridge firmware.
REM Usage: flash.bat COM5 [env]      env = nodemcu (default) or esp01
REM
REM NodeMCU: just plug the board's USB into the PC, nothing else to do.
REM ESP-01 : GPIO0 -> GND, CH_PD -> 3.3V, then power-cycle before flashing.
setlocal
if "%~1"=="" (
    echo Usage: flash.bat COMx [nodemcu^|esp01]
    pause
    exit /b 1
)
set "PORT=%~1"
set "ENV=%~2"
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
echo Flashing env %ENV% on %PORT%
"%PIO%" -m platformio run -e %ENV% -t upload --upload-port %PORT%
pause