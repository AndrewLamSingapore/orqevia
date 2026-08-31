@echo off
setlocal EnableExtensions EnableDelayedExpansion
title JARVIS Protected Portal Smoke

set "SCRIPT=%~dp0scripts\smoke_portal_result.py"
set "REPORT=%~dp0portal-smoke-result.json"
set "CONTAINER="

if not exist "%SCRIPT%" (
  echo ERROR: Portal smoke script is missing. Keep this file in the JARVIS Operations Pack.
  pause
  exit /b 1
)

for /f "usebackq delims=" %%C in (`docker ps --filter "label=com.docker.compose.project=prime" --filter "label=com.docker.compose.service=prime" --format "{{.Names}}"`) do (
  if defined CONTAINER (
    echo ERROR: More than one canonical PRIME container is running.
    pause
    exit /b 1
  )
  set "CONTAINER=%%C"
)

if not defined CONTAINER (
  echo ERROR: The canonical PRIME container is not running.
  pause
  exit /b 1
)

docker exec "!CONTAINER!" sh -c "test -n \"$PORTAL_RESULT_TOKEN\"" >nul 2>&1
if errorlevel 1 (
  echo ERROR: The protected Portal credential is not configured.
  pause
  exit /b 1
)

echo Copying the non-physical smoke harness into !CONTAINER!...
docker cp "%SCRIPT%" "!CONTAINER!:/tmp/smoke_portal_result.py" >nul
if errorlevel 1 goto :failed

echo Writing and reading one synthetic non-physical Portal result...
docker exec "!CONTAINER!" python /tmp/smoke_portal_result.py --generate-safe-smoke --output /tmp/portal-smoke-result.json
if errorlevel 1 goto :failed

docker cp "!CONTAINER!:/tmp/portal-smoke-result.json" "%REPORT%" >nul
if errorlevel 1 goto :failed

echo.
echo JARVIS protected Portal smoke completed successfully.
echo Report: %REPORT%
echo The credential was not displayed or written to the report.
echo No physical action or scientific claim was authorized.
echo.
pause
exit /b 0

:failed
echo.
echo ERROR: Portal smoke stopped with exit code !ERRORLEVEL!.
echo PRIME and its Docker volumes were not changed.
echo.
pause
exit /b 1
