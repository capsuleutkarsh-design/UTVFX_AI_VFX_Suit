@echo off
setlocal EnableExtensions
:: Contour VFX installer. All the work happens in first_setup.py; this file only finds
:: a Python 3.10 or 3.11 to run it with. first_setup.py then builds its own portable
:: Python 3.10 in python_base\ and installs requirements-lock.txt into it.
:: Extra arguments are passed on, for example:  install.bat --check
cd /d "%~dp0"
echo ==============================================
echo  Contour VFX setup
echo ==============================================

set "VERSION_CHECK=import sys; sys.exit(0 if sys.version_info[:2] in ((3,10),(3,11)) else 1)"

:: 1. An existing python_base (portable Python from an earlier run)
if exist "python_base\python.exe" (
    "python_base\python.exe" -c "%VERSION_CHECK%" >nul 2>&1 && (
        set "PY_CMD="python_base\python.exe""
        goto :run
    )
)

:: 2. The Windows py launcher
where py >nul 2>&1 && (
    py -3.11 -c "%VERSION_CHECK%" >nul 2>&1 && ( set "PY_CMD=py -3.11" & goto :run )
    py -3.10 -c "%VERSION_CHECK%" >nul 2>&1 && ( set "PY_CMD=py -3.10" & goto :run )
)

:: 3. uv (it downloads a Python 3.10 by itself if none is installed)
set "UV_EXE="
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV_EXE for /f "delims=" %%U in ('where uv 2^>nul') do if not defined UV_EXE set "UV_EXE=%%U"
if defined UV_EXE (
    set "PY_CMD="%UV_EXE%" run --no-project --python 3.10 python"
    goto :run
)

:: 4. python on PATH, only if it is 3.10 or 3.11
where python >nul 2>&1 && (
    python -c "%VERSION_CHECK%" >nul 2>&1 && ( set "PY_CMD=python" & goto :run )
    for /f "delims=" %%V in ('python -c "import sys; print(sys.version.split()[0])" 2^>nul') do set "FOUND_VER=%%V"
)

echo.
echo [ERROR] No Python 3.10 or 3.11 found.
if defined FOUND_VER echo         The python on PATH is %FOUND_VER%, which is not supported.
echo         torch 2.5.1+cu121 and mediapipe^<0.10.10 have no wheels for Python 3.12 or newer.
echo         Install Python 3.11 from https://www.python.org/downloads/windows/
echo         (or install uv: https://docs.astral.sh/uv/) and run install.bat again.
pause
exit /b 1

:run
echo [INFO] Running first_setup.py with: %PY_CMD%
%PY_CMD% first_setup.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Setup did not finish. Read the messages above, fix the problem and run install.bat again.
    pause
    exit /b 1
)
echo.
echo [SUCCESS] Installation complete. Start the app with run.bat
pause
exit /b 0
