@echo off
REM =========================================================================
REM  Build FortiGate-to-FTD Converter as a standalone Windows .exe
REM =========================================================================
REM  Prerequisites:
REM    - Python 3.8+ with pip
REM    - Internet access (first run only, to install dependencies)
REM
REM  Output:
REM    FortiGateToFTDTool\dist\FortiGate-to-FTD-Converter.exe
REM =========================================================================

echo.
echo ============================================================
echo   FortiGate to FTD Converter - Build Script
echo ============================================================
echo.

REM Install dependencies if needed
echo [1/3] Installing dependencies...
pip install pyyaml requests urllib3 pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [WARN] pip install had warnings - continuing anyway...
)
echo       Done.
echo.

REM Change to the package directory where all modules live
cd /d "%~dp0FortiGateToFTDTool"

echo [2/3] Building executable with PyInstaller...
echo       This may take a minute...
echo.

pyinstaller --onefile --windowed ^
    --name "FortiGate-to-FTD-Converter" ^
    --icon "app_icon.ico" ^
    --paths "." ^
    --hidden-import yaml ^
    --hidden-import requests ^
    --hidden-import urllib3 ^
    --hidden-import address_converter ^
    --hidden-import address_group_converter ^
    --hidden-import service_converter ^
    --hidden-import service_group_converter ^
    --hidden-import policy_converter ^
    --hidden-import route_converter ^
    --hidden-import interface_converter ^
    --hidden-import common ^
    --hidden-import concurrency_utils ^
    --hidden-import ftd_api_base ^
    --hidden-import platform_profiles ^
    --hidden-import fortigate_converter ^
    --hidden-import ftd_api_importer ^
    --hidden-import ftd_api_cleanup ^
    --clean ^
    gui_app.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Check the output above for details.
    echo.
    pause
    exit /b 1
)

echo.
echo [3/3] Copying executable to project root...
copy /Y "dist\FortiGate-to-FTD-Converter.exe" "%~dp0FortiGate-to-FTD-Converter.exe" >nul 2>&1

echo.
echo ============================================================
echo   BUILD COMPLETE
echo ============================================================
echo.
echo   Executable:  FortiGate-to-FTD-Converter.exe
echo   Location:    %~dp0FortiGate-to-FTD-Converter.exe
echo.
echo   You can distribute this single .exe file to users.
echo   No Python installation required on the target machine.
echo.
echo   NOTE: If Windows Defender flags the .exe, you may need
echo   to add an exclusion or sign the executable.
echo ============================================================
echo.
pause
