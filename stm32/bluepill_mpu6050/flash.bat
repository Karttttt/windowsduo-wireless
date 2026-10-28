@echo off
REM Flash the STM32 firmware through ST-Link V2 (SWD).
REM Build first if firmware.bin is missing, then upload with OpenOCD.
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
"%PIO%" -m platformio run -e bluepill -t upload %*
echo.
echo If upload failed with "unable to open ... ST-Link", use the serial ISP route:
echo   BOOT0 jumper to 1, reset, then stm32flash -w .pio\build\bluepill\firmware.bin -v -g 0x0 COMx
pause