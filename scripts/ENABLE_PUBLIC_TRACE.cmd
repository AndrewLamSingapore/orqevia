@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable-public-trace.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo JARVIS public trace activation failed with exit code %RC%.
exit /b %RC%
