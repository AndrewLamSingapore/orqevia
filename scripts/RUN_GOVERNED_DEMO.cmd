@echo off
setlocal
title JARVIS PRIME - Governed Execution Demo
cd /d "%~dp0"

echo.
echo ================================================
echo   JARVIS PRIME - GOVERNED EXECUTION DEMO
echo ================================================
echo.
echo This runs one real read-only governed task through
echo PRIME and verifies its sanitized trace in J Console.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-governed-demo.ps1"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo Governed execution verification did not complete.
  echo Take a photo of the message above and send it to ChatGPT.
  echo.
  pause
  exit /b %RC%
)

echo Governed execution verified successfully.
echo.
pause
exit /b 0
