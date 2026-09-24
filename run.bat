@echo off
echo Starting Contour VFX...
set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python_base\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=%BASE_DIR%python_base\python.exe"
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python environment not found!
    echo Please run FIRST_SETUP.bat first to set up the environment.
    pause
    exit /b 1
)

rem Append, so the output of a session that crashed is still there after the next launch.
echo ===== %DATE% %TIME% ===== >> "%BASE_DIR%crash.log"
"%PYTHON_EXE%" -u "%BASE_DIR%main.py" >> "%BASE_DIR%crash.log" 2>&1
pause
