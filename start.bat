@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3.10+ from python.org and tick "Add to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Could not create a virtual environment.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
echo Installing packages (first run can take a minute)...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package install failed.
  pause
  exit /b 1
)

echo.
echo Starting dashboard at http://127.0.0.1:8765/?demo=1
echo Close this window to stop the server.
echo.

start "" "http://127.0.0.1:8765/?demo=1"
python -m uvicorn app:app --host 127.0.0.1 --port 8765
pause
