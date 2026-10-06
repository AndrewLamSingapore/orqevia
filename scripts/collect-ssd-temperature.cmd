@echo off
rem Fixed task action: no caller arguments are expanded or forwarded. Install
rem only in the protected broker directory after ACL and source review.
"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\ABEX\PrimeThermal\collect-ssd-temperature.ps1"
exit /b %ERRORLEVEL%
