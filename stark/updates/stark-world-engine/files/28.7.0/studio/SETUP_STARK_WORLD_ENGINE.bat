@echo off
REM Stark World Engine - friendly setup. Double-click me. Your browser opens the setup page;
REM this window stays open while you set up (close it when you are done).
REM If this file was moved next to setup_wizard.py it uses that folder, otherwise the parent folder.
REM Path safety: the folder is read once (delayed expansion off, so a bang survives) and then only used
REM through delayed expansion, so ampersand, caret, percent, brackets etc. in it stay plain text.
setlocal EnableExtensions DisableDelayedExpansion
title Stark World Engine setup
set "HERE=%~dp0"
setlocal EnableDelayedExpansion
set "APP=!HERE!"
if not exist "!HERE!setup_wizard.py" set "APP=!HERE!..\"
cd /d "!APP!"
echo.
echo   Starting Stark World Engine setup... your browser will open in a moment.
echo.
set "PY="
if exist "!APP!runtime\python\python.exe" set "PY="!APP!runtime\python\python.exe""
if defined PY goto :run
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :run
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :run
echo   Python 3.10 or newer is needed and was not found.
echo   Get it free from https://www.python.org/downloads/  - tick "Add python.exe to PATH",
echo   then double-click this file again.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:run
!PY! "!APP!setup_wizard.py"
if not errorlevel 1 exit /b 0
echo.
echo   Setup stopped with an error. The details are in .claude\setup_wizard.log
pause
exit /b 1
