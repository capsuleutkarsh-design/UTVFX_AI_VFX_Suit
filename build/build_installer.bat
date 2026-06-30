@echo off
cd /d "%~dp0.."
echo Building UTVFX AI & VFX Suit...
echo Activating Virtual Environment...
call venv\Scripts\activate.bat

echo Running PyInstaller...
pyinstaller --noconfirm --onedir --windowed ^
  --icon="build\app_icon.ico" ^
  --name "UTVFX_AI_VFX_Tool" ^
  --add-data "core_ui;core_ui/" ^
  --add-data "plugins;plugins/" ^
  --add-data "CorridorKeyModule;CorridorKeyModule/" ^
  main.py

echo Build completed.

echo Generating Inno Setup Installer...
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    %ISCC% "build\installer.iss"
    echo Installer successfully generated in Output folder.
) else (
    echo Error: Inno Setup 6 not found at %ISCC%. Please install Inno Setup 6 to generate the installer.
)
pause
