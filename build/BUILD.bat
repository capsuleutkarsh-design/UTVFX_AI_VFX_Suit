@echo off
setlocal EnableDelayedExpansion
:: ==========================================================================
::  Contour VFX - one-click build
::
::    step 1  Python : build_app.py stages the app (source + python_base) into
::                     build\stage\ContourVFX, makes ContourVFX.exe and checks
::                     that the staged app starts
::    step 2  Inno   : packs the stage into build\Output\ContourVFX_Setup_<ver>.exe
::                     plus ContourVFX_Setup_<ver>-1.bin, -2.bin ... (the payload
::                     is over 2 GB, so Inno splits it; ship them all together)
::
::  Usage:
::    BUILD.bat              full build
::    BUILD.bat clean        also reinstall the build tools first
::    BUILD.bat stage        stop after step 1 (no installer)
::    BUILD.bat installer    skip step 1, re-run Inno on the last stage
::    BUILD.bat check        only check that everything needed is there
::    ... noverify           skip starting the staged app (any mode)
:: ==========================================================================

pushd "%~dp0.." >nul
set "ROOT=%cd%"
popd >nul
set "BUILD_DIR=%ROOT%\build"
set "PY=%ROOT%\python_base\python.exe"
set "MODE=all"
set "EXTRA="
for %%A in (%*) do (
    if /i "%%~A"=="clean"     set "MODE=all" & set "EXTRA=!EXTRA! --clean"
    if /i "%%~A"=="stage"     set "MODE=stage"
    if /i "%%~A"=="installer" set "MODE=installer"
    if /i "%%~A"=="check"     set "MODE=check"
    if /i "%%~A"=="noverify"  set "EXTRA=!EXTRA! --no-verify"
)

echo.
echo ================================================================
echo   Contour VFX build   mode: %MODE%%EXTRA%
echo   %ROOT%
echo ================================================================
echo.

if not exist "%PY%" (
    echo [build] ERROR: python_base\python.exe not found. Run install.bat first.
    goto :failed
)

:: ---------- Inno Setup ------------------------------------------------------
set "ISCC="
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) do (
    if exist %%P if not defined ISCC set "ISCC=%%~P"
)
if not defined ISCC (
    if /i not "%MODE%"=="stage" (
        echo [build] ERROR: Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php
        echo         or run "BUILD.bat stage" to build only the app folder.
        goto :failed
    )
) else (
    echo [build] Inno Setup: "!ISCC!"
)

if /i "%MODE%"=="check" (
    "%PY%" "%BUILD_DIR%\build_app.py" --check || goto :failed
    goto :done
)

:: ---------- step 1: stage ---------------------------------------------------
if /i not "%MODE%"=="installer" (
    "%PY%" "%BUILD_DIR%\build_app.py" %EXTRA% || goto :failed
)
if /i "%MODE%"=="stage" goto :done

:: ---------- step 2: installer -------------------------------------------------
if not exist "%BUILD_DIR%\stage\ContourVFX\ContourVFX.exe" (
    echo [build] ERROR: no staged app. Run BUILD.bat without "installer" first.
    goto :failed
)
if exist "%BUILD_DIR%\Output" rmdir /s /q "%BUILD_DIR%\Output"
echo [build] Packing the installer (compressing ~6 GB; this takes a while)...
"%ISCC%" /Q "%BUILD_DIR%\installer.iss" || goto :failed
echo.
echo [build] Installer files in %BUILD_DIR%\Output:
dir /b "%BUILD_DIR%\Output"
echo [build] Ship the .exe and every .bin together, in one folder.

:done
echo.
echo [build] Done.
if not defined NOPAUSE pause
exit /b 0

:failed
echo.
echo [build] BUILD FAILED.
if not defined NOPAUSE pause
exit /b 1
