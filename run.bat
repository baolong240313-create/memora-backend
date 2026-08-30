@echo off
cd /d "%~dp0"

:: Make sure Python itself is available.
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python was not found on your PATH.
    echo Please install it from https://www.python.org/downloads/
    echo and make sure to tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

echo Installing dependencies...
:: "python -m pip" works even when the bare "pip" command isn't on PATH.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency install failed. See the error above.
    pause
    exit /b 1
)

echo.
echo Starting Memora... (keep this window open)
python app.py
pause