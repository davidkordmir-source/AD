@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_Activate_Offline.bat"
if errorlevel 1 exit /b 1
"%SV_RUNTIME%\python.exe" "%SV_RUNTIME%\Scripts\conda-unpack-script.py"
if errorlevel 1 exit /b 1
call "%~dp0_Activate_Offline.bat"
if errorlevel 1 exit /b 1
"%SV_RUNTIME%\python.exe" "%~dp0scripts\check_offline.py" --runtime "%SV_RUNTIME%" --report "%~dp0OFFLINE_CHECK.json"
exit /b %errorlevel%
