@echo off
echo ==============================================
echo Installing UTVFX AI ^& VFX Suit Environment...
echo ==============================================

:: Check if Python is installed
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.10 or newer and try again.
    pause
    exit /b 1
)

:: Check if python_base already exists
IF EXIST "python_base\Scripts\python.exe" (
    echo [INFO] Virtual environment already exists in python_base.
    echo Skipping environment creation...
) ELSE IF EXIST "python_base\python.exe" (
    echo [INFO] Portable Python environment found in python_base.
    echo Skipping environment creation...
) ELSE (
    echo [INFO] Creating Python virtual environment in 'python_base'...
    python -m venv python_base
    IF %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Determine Python executable path (venv vs portable)
set "PYTHON_EXE=python_base\Scripts\python.exe"
IF NOT EXIST "%PYTHON_EXE%" (
    set "PYTHON_EXE=python_base\python.exe"
)

:: Install dependencies
echo [INFO] Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip

echo [INFO] Installing requirements...
"%PYTHON_EXE%" -m pip install -r requirements.txt

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ==============================================
echo [SUCCESS] Installation complete!
echo You can now run the tool using run.bat
echo ==============================================
pause
