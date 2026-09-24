@echo off
rem Render a saved project without the window. Examples:
rem   render.bat shot.contour
rem   render.bat shot.contour --node Depth1 --frames 1001-1050
rem   render.bat shot.contour --list
set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python_base\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python environment not found. Run install.bat first.
    exit /b 2
)
pushd "%BASE_DIR%"
"%PYTHON_EXE%" -u "%BASE_DIR%render.py" %*
set "CODE=%ERRORLEVEL%"
popd
exit /b %CODE%
