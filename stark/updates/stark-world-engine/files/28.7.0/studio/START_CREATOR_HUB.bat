@echo off
cd /d "%~dp0"
set "PY=python"
if exist "runtime\python\python.exe" set "PY=runtime\python\python.exe"
"%PY%" -u obs_bridge.py
start "" "%PY%" -u auto_editor.py --watch
"%PY%" -u creator_hub.py --phone
pause
