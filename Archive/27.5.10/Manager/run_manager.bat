@echo off
setlocal
cd /d "%~dp0"
python -u manager_app\main.py
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo.
  echo [POS MANAGER] stopped with exit code %ERR%.
  if exist logs\startup_error.log type logs\startup_error.log
  pause
)
exit /b %ERR%
