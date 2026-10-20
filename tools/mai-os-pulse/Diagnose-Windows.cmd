@echo off
set "pulse_python=%LOCALAPPDATA%\MaiOsPulse\.venv\Scripts\python.exe"
if not exist "%pulse_python%" (
  echo Pulse Python environment was not found. Run Install-Windows.cmd first.
  pause
  exit /b 1
)
"%pulse_python%" -u "%~dp0diagnose.py" "%~dp0Pulse-Diagnostics.txt"
pause
