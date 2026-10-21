@echo off
setlocal
cd /d "%~dp0"
echo Activating private runtime...
call "%~dp0_Activate_Offline.bat"
if errorlevel 1 exit /b 1
echo Updating local runtime paths...
"%SV_RUNTIME%\python.exe" "%SV_RUNTIME%\Scripts\conda-unpack-script.py"
if errorlevel 1 exit /b 1
echo Activating private runtime...
call "%~dp0_Activate_Offline.bat"
if errorlevel 1 exit /b 1
echo Checking native GIS and GUI...
"%SV_RUNTIME%\python.exe" "%~dp0scripts\check_offline.py" --runtime "%SV_RUNTIME%" --report "%~dp0OFFLINE_CHECK.json"
exit /b %errorlevel%
