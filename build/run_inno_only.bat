@echo off
cd /d "%~dp0.."
echo Generating Inno Setup Installer...
set ISCC="C:\Program Files\Inno Setup 7\ISCC.exe"
if exist %ISCC% (
    %ISCC% "build\installer.iss"
    echo Installer successfully generated in Output folder.
) else (
    echo Error: Inno Setup 7 not found at %ISCC%. Please install Inno Setup 7 to generate the installer.
)
pause
