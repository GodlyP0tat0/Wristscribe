@echo off
REM WristScribe launcher for Windows.
REM Double-click it: the first run installs everything, every run starts the receiver.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [WristScribe] First run: creating a Python environment...
    py -3 -m venv .venv || python -m venv .venv
    if errorlevel 1 goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 goto :failed
)

if not exist "config.toml" (
    ".venv\Scripts\python.exe" -m wristscribe init
)

".venv\Scripts\python.exe" -m wristscribe run
pause
exit /b

:nopython
echo.
echo Python 3.11 or newer was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
pause
exit /b 1

:failed
echo.
echo Installing the dependencies failed. Scroll up to see the error.
pause
exit /b 1
