@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_Activate_Offline.bat"
if errorlevel 1 exit /b 1
if not exist "%LOCALAPPDATA%\FastViewshed\Logs" mkdir "%LOCALAPPDATA%\FastViewshed\Logs"
"%SV_RUNTIME%\python.exe" "%~dp0scripts\check_offline.py" --runtime "%SV_RUNTIME%" --report "%~dp0OFFLINE_CHECK.json" > "%LOCALAPPDATA%\FastViewshed\Logs\BrandingCheck.log" 2>&1
exit /b %errorlevel%
