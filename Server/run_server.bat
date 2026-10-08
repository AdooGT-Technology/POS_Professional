@echo off
setlocal
cd /d "%~dp0"
title POS Professional V27.5.7 - Central Server
where python >nul 2>&1
if errorlevel 1 (echo Python is not available on PATH.&pause&exit /b 9009)
python -u run_server.py
set "EC=%ERRORLEVEL%"
echo.
echo POS V27.5.7 Central Server stopped with exit code %EC%.
pause
exit /b %EC%
