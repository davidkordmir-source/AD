@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Apply_3_6_Update.ps1"
set "FV_FIX_RESULT=%errorlevel%"
pause
exit /b %FV_FIX_RESULT%
