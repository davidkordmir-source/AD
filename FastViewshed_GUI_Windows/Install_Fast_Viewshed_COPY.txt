@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_offline.ps1"
set "SV_INSTALL_RESULT=%errorlevel%"
if not "%SV_INSTALL_RESULT%"=="0" echo Installation failed. No online installation was attempted.
if /i not "%~1"=="--quiet" pause
exit /b %SV_INSTALL_RESULT%
