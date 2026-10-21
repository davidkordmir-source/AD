@echo off
setlocal
cd /d "%~dp0"
call "%~dp0Install_Fast_Viewshed.bat" --quiet
if errorlevel 1 goto failed
call "%~dp0_Activate_Offline.bat"
if errorlevel 1 goto failed
"%SV_RUNTIME%\pythonw.exe" "%~dp0FastViewshed_GUI.py"
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Keep this message and OFFLINE_CHECK.json for troubleshooting.
echo Startup logs are in %%TEMP%%\FastViewshed_logs
pause
exit /b 1
