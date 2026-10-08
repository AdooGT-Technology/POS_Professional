@echo off
setlocal
cd /d "%~dp0"
title POS Professional V27.5.7 - Server Runtime Setup
python -u setup_runtime.py
set "EC=%ERRORLEVEL%"
echo.
if "%EC%"=="0" (echo Server runtime is ready.) else (echo Server runtime setup failed with exit code %EC%.)
pause
exit /b %EC%
