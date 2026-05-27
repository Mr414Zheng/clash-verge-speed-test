@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=py"
)

if "%PYTHON_EXE%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if "%PYTHON_EXE%"=="" (
    echo Python was not found. Please install Python or create .venv first.
    pause
    exit /b 1
)

echo Starting Clash Verge Speed Tester...
echo.
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
"%PYTHON_EXE%" -m streamlit run app.py --server.headless=false --browser.gatherUsageStats=false

if errorlevel 1 (
    echo.
    echo Failed to start the app. If dependencies are missing, run:
    echo "%PYTHON_EXE%" -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

endlocal
