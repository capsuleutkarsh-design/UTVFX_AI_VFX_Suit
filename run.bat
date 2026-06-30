@echo off
echo Starting UTVFX AI ^& VFX Suit...
set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python_base\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Portable Python environment not found!
    echo Please make sure the 'python_base' folder exists.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -u "%BASE_DIR%main.py"
pause
