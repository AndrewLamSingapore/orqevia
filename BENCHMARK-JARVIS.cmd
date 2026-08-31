@echo off
setlocal EnableExtensions EnableDelayedExpansion
title JARVIS Local Model Benchmark

set "SCRIPT=%~dp0scripts\benchmark_local_models.py"
set "REPORT=%~dp0local-model-benchmark.json"
set "CONTAINER="

if not exist "%SCRIPT%" (
  echo ERROR: Benchmark script is missing. Keep this file in the JARVIS Operations Pack.
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

echo Copying the private benchmark into !CONTAINER!...
docker cp "%SCRIPT%" "!CONTAINER!:/tmp/benchmark_local_models.py" >nul
if errorlevel 1 goto :failed

echo Running benchmark against the Docker-internal Ollama service...
docker exec "!CONTAINER!" python /tmp/benchmark_local_models.py --base-url http://ollama:11434 --allow-docker-internal --output /tmp/local-model-benchmark.json
if errorlevel 1 goto :failed

docker cp "!CONTAINER!:/tmp/local-model-benchmark.json" "%REPORT%" >nul
if errorlevel 1 goto :failed

echo.
echo JARVIS local model benchmark completed successfully.
echo Report: %REPORT%
echo No prompts were sent outside the private Docker network.
echo.
pause
exit /b 0

:failed
echo.
echo ERROR: Benchmark stopped with exit code !ERRORLEVEL!.
echo PRIME and its Docker volumes were not changed.
echo.
pause
exit /b 1
