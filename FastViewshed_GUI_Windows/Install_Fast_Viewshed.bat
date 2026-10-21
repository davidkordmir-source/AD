@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_offline.ps1" > "%~dp0OFFLINE_INSTALL.log" 2>&1
set "SV_INSTALL_RESULT=%errorlevel%"
type "%~dp0OFFLINE_INSTALL.log"
if not "%SV_INSTALL_RESULT%"=="0" echo Installation failed. No online installation was attempted.
if /i not "%~1"=="--quiet" pause
exit /b %SV_INSTALL_RESULT%
