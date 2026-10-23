@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build_Custom_Setup.ps1"
set "FV_BUILD_RESULT=%errorlevel%"
if not "%FV_BUILD_RESULT%"=="0" echo Build failed. Read the message above.
pause
exit /b %FV_BUILD_RESULT%
