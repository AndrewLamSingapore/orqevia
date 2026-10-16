@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ORQEVIA_SCRIPT=%~dp0scripts\orqevia.ps1"

if not exist "%ORQEVIA_SCRIPT%" (
  echo ORQEVIA operations script is missing: %ORQEVIA_SCRIPT%
  exit /b 1
)

if not "%~1"=="" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORQEVIA_SCRIPT%" %*
  exit /b !ERRORLEVEL!
)

:menu
cls
echo.
echo   ORQEVIA LOCAL OPERATIONS
echo   =======================
echo   1. Start and open Control Surface
echo   2. Status and safety checks
echo   3. Diagnose runtime
echo   4. Repair and consolidate
echo   5. Open Control Surface
echo   6. Stop ORQEVIA ^(data retained^)
echo   7. Exit
echo.
set /p "choice=Select 1-7: "

if "%choice%"=="1" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORQEVIA_SCRIPT%" -Action start
if "%choice%"=="2" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORQEVIA_SCRIPT%" -Action status
if "%choice%"=="3" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORQEVIA_SCRIPT%" -Action doctor
if "%choice%"=="4" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORQEVIA_SCRIPT%" -Action repair
if "%choice%"=="5" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORQEVIA_SCRIPT%" -Action open
if "%choice%"=="6" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORQEVIA_SCRIPT%" -Action stop
if "%choice%"=="7" exit /b 0
echo.
pause
goto menu

