@echo off
cd /d "%~dp0.."
echo Building Contour VFX...
echo Activating Virtual Environment...
call venv\Scripts\activate.bat

echo Creating Models ZIP (this might take a while)...
python scripts\build_models_zip.py

echo Running PyInstaller...
pyinstaller --noconfirm ContourVFX.spec

echo Build completed.

echo Generating Inno Setup Installer...
set ISCC="C:\Program Files\Inno Setup 7\ISCC.exe"
if exist %ISCC% (
    %ISCC% "build\installer.iss"
    echo Installer successfully generated in Output folder.
) else (
    echo Error: Inno Setup 7 not found at %ISCC%. Please install Inno Setup 7 to generate the installer.
)
pause
