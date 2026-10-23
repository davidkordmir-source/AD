@echo off
setlocal
cd /d "%~dp0"
call "%~dp0Install_Fast_Viewshed.bat" --quiet
if errorlevel 1 exit /b 1
call "%~dp0_Activate_Offline.bat"
if errorlevel 1 exit /b 1
"%SV_RUNTIME%\python.exe" "%~dp0scripts\check_offline.py" --runtime "%SV_RUNTIME%" --report "%~dp0OFFLINE_CHECK.json"
set "SV_CHECK_RESULT=%errorlevel%"
if /i not "%~1"=="--quiet" pause
exit /b %SV_CHECK_RESULT%
