@echo off
setlocal
cd /d "%~dp0"
title POS Professional - Manager WebView2 Diagnostic
set PYWEBVIEW_LOG=debug
set PYWEBVIEW_GUI=edgechromium
set PYTHONNET_RUNTIME=netfx
call run_manager.bat
