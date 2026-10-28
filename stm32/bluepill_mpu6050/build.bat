@echo off
REM Build the STM32 firmware.
REM Why C:\duo: arm-none-eabi toolchain cannot open linker scripts under a
REM non-ASCII path, and it needs a temp dir inside the project tree.
setlocal
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
cd /d "C:\duo\WindowsDuo\stm32\bluepill_mpu6050"
"%PIO%" -m platformio run -e bluepill %*
pause