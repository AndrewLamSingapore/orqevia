@echo off
echo %~1 | findstr /I "Username" >nul
if %ERRORLEVEL% EQU 0 (
  echo x-access-token
  exit /b 0
)
gh auth token
