@echo off
REM ACI installer - double-click to install on Windows.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0install.ps1"
echo.
pause
