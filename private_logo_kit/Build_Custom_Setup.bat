@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
    powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Build_Custom_Setup.ps1"
) else (
    powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Build_Custom_Setup.ps1" -LogoFile "%~1"
)
set "FV_BUILD_RESULT=%errorlevel%"
if not "%FV_BUILD_RESULT%"=="0" echo Build failed. Read the message above.
pause
exit /b %FV_BUILD_RESULT%
