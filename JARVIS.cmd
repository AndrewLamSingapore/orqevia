@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "JARVIS_SCRIPT=%~dp0scripts\jarvis.ps1"

if not exist "%JARVIS_SCRIPT%" (
  echo JARVIS operations script is missing: %JARVIS_SCRIPT%
  exit /b 1
)

if not "%~1"=="" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" %*
  exit /b !ERRORLEVEL!
)

:menu
cls
echo.
echo   JARVIS LOCAL OPERATIONS
echo   =======================
echo   1. Start and open Control Surface
echo   2. Status and safety checks
echo   3. Diagnose runtime
echo   4. Repair and consolidate
echo   5. Open Control Surface
echo   6. Stop JARVIS ^(data retained^)
echo   7. Exit
echo   8. Ask JARVIS to check or review something
echo   9. Restart safely when idle
echo   V. Verify JARVIS
echo.
set /p "choice=Select an option: "

if "%choice%"=="1" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action start
if "%choice%"=="2" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action status
if "%choice%"=="3" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action doctor
if "%choice%"=="4" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action repair
if "%choice%"=="5" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action open
if "%choice%"=="6" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action stop
if "%choice%"=="7" exit /b 0
if "%choice%"=="8" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action ask
if "%choice%"=="9" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action restart
if /i "%choice%"=="V" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SCRIPT%" -Action verify
echo.
pause
goto menu

