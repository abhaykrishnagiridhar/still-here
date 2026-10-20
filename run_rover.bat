@echo off
rem Starts the operator website against the real rover (its camera and command link).
rem Double-click it, or run it from any folder. Extra options pass straight through, for example:
rem     run_rover.bat --rover 192.168.153.44
rem     run_rover.bat --port 8060
rem Before starting: the laptop and the rover must be on the same Wi-Fi (the hotspot), and the
rem rover must be powered. Close any browser tab showing the rover's /stream: it serves one viewer.

cd /d "%~dp0laptop"

if not exist ".venv\Scripts\python.exe" (
    echo The laptop's Python environment is missing: laptop\.venv
    echo Create it first, as described in the README, then run this again.
    pause
    exit /b 1
)

echo Starting the operator website for the real rover...
echo Open the address printed below. Press Ctrl+C in this window to stop.
echo.
".venv\Scripts\python.exe" server.py --port 8050 %*

echo.
echo The server stopped. If it said the port is in use, close the other server or run:
echo     run_rover.bat --port 8060
pause
