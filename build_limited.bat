@echo off
REM =========================================================================
REM  Build Firewall Migration Tool from a named limited/full profile
REM =========================================================================
REM  Usage:
REM    build_limited.bat
REM        Builds the default restricted profile: fortigate_to_ftd
REM
REM    build_limited.bat fortigate_to_ftd
REM        Builds the FortiGate -> Cisco FTD restricted executable
REM
REM    build_limited.bat fortigate_to_ftd 1.7.6
REM        Builds that profile with version 1.7.6
REM
REM    build_limited.bat --list
REM        Lists available profiles from build_profiles.json
REM
REM    build_limited.bat fortigate_to_ftd 1.7.6 --dry-run
REM        Prints the generated PyInstaller command without building
REM
REM    build_limited.bat fortigate_to_ftd 1.7.6 --no-cleanup
REM        Builds without the Cleanup tab or cleanup modules
REM
REM    build_limited.bat fortigate_to_ftd_no_cleanup
REM        Same as fortigate_to_ftd but cleanup disabled via profile
REM =========================================================================

setlocal
cd /d "%~dp0"

if /I "%~1"=="--list" (
    py -3.14 "%~dp0build_profile.py" --list
    exit /b %ERRORLEVEL%
)

set "PROFILE=%~1"
if "%PROFILE%"=="" set "PROFILE=fortigate_to_ftd"

set "VERSION_ARG="
if not "%~2"=="" set "VERSION_ARG=--version %~2"

set "EXTRA_ARGS=%~3 %~4 %~5 %~6 %~7 %~8 %~9"

py -3.14 "%~dp0build_profile.py" "%PROFILE%" %VERSION_ARG% %EXTRA_ARGS%
exit /b %ERRORLEVEL%
