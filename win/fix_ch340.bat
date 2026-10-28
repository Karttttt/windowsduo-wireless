@echo off
REM Repair the CH340 COM-port collision (device shows "problem code 31" and no COM exists).
REM Double-click this file; it will ask for admin (UAC) and print what it did.
setlocal
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_ch340.ps1"
echo.
pause