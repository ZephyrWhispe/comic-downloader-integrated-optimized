@echo off
cd /d %~dp0
chcp 65001 > nul
echo [1/4] Checking Python environment...

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python and add to PATH.
    pause
    exit /b 1
)

echo [2/4] Creating virtual environment (venv)...
if not exist venv (
    python -m venv venv
)

if %errorlevel% neq 0 (
    echo [WARNING] Failed to create venv.
) else (
    echo Activating venv...
    call venv\Scripts\activate
)

echo [3/4] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo [4/4] Installing Playwright (Chromium)...
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo [WARNING] Playwright installation might be incomplete.
)

echo.
echo ==================================================
echo [SUCCESS] Installation complete!
echo You can now run run-gui.bat.
echo ==================================================
echo.
pause
