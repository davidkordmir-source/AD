@echo off
rem Called inside the launcher's SETLOCAL. No external Conda is required.
set "SV_RUNTIME=%~dp0runtime_offline"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
set "GDAL_DATA="
set "PROJ_LIB="
set "PROJ_DATA="
set "CONDA_PREFIX="
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
if not exist "%SV_RUNTIME%\Scripts\activate.bat" exit /b 1
call "%SV_RUNTIME%\Scripts\activate.bat"
if errorlevel 1 exit /b 1
set "GDAL_DATA=%SV_RUNTIME%\Library\share\gdal"
set "PROJ_DATA=%SV_RUNTIME%\Library\share\proj"
set "PROJ_LIB=%PROJ_DATA%"
set "PROJ_NETWORK=OFF"
exit /b 0
