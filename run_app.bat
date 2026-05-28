@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=py -3.10"
    )
)

if "%PYTHON_EXE%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=python"
    )
)

if "%PYTHON_EXE%"=="" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=py"
    )
)

if "%PYTHON_EXE%"=="" (
    echo ERROR: Python 3.10 or newer was not found.
    echo Install Python 3.10+ and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv...
    %PYTHON_EXE% -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create .venv.
        echo Check that Python can create virtual environments, then try again.
        pause
        exit /b 1
    )
)

set "PYTHON_EXE=.venv\Scripts\python.exe"

echo Installing dependencies from requirements.txt...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies from requirements.txt.
    echo Check your network connection and pip output above, then try again.
    pause
    exit /b 1
)

echo Starting Clash Verge Speed Tester...
echo.
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
"%PYTHON_EXE%" -m streamlit run app.py --server.headless=false --browser.gatherUsageStats=false

if errorlevel 1 (
    echo.
    echo ERROR: Failed to start the Streamlit app.
    echo Review the error output above, then try again.
    echo.
    pause
    exit /b 1
)

endlocal
