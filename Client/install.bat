@echo off
setlocal
cd /d "%~dp0"
title POS Professional V27.5.7 - Client Runtime Setup
python -u setup_runtime.py
set "EC=%ERRORLEVEL%"
echo.
if "%EC%"=="0" (echo Client runtime is ready.) else (echo Client runtime setup failed with exit code %EC%.)
pause
exit /b %EC%
