@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Apply_Path_Fix.ps1"
set "FV_FIX_RESULT=%errorlevel%"
pause
exit /b %FV_FIX_RESULT%
