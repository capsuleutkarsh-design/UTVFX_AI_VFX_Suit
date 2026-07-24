@echo off
echo Starting UTVFX AI ^& VFX Suit...
set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python_base\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=%BASE_DIR%python_base\python.exe"
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python environment not found!
    echo Please run install.bat first to set up the environment.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -u "%BASE_DIR%main.py" > "%BASE_DIR%crash.log" 2>&1
pause
