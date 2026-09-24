[Setup]
; AppId must never change: Windows uses it to find this app for upgrades and uninstall.
AppId={{7C2E4B1A-5D3F-4E8A-9B61-0C4F2A7D93E5}
AppName=Contour VFX
AppVersion=2.0.0-beta
AppPublisher=Utkarsh Tripathi
DefaultDirName={localappdata}\Programs\Contour VFX
PrivilegesRequired=lowest
DefaultGroupName=Contour VFX
OutputDir=..\releases
OutputBaseFilename=ContourVFX_Setup
SetupIconFile=..\branding\app_icon.ico
WizardImageFile=..\branding\wizard_large.bmp
WizardSmallImageFile=..\branding\wizard_small.bmp
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DiskSpanning=yes
DiskSliceSize=2000000000

[Files]
Source: "extract_models.ps1"; Flags: dontcopy
Source: "..\dist\ContourVFX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Contour VFX"; Filename: "{app}\ContourVFX.exe"; IconFilename: "{app}\ContourVFX.exe"
Name: "{autodesktop}\Contour VFX"; Filename: "{app}\ContourVFX.exe"; IconFilename: "{app}\ContourVFX.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Code]
var
  ModelsPage: TInputFileWizardPage;

procedure InitializeWizard;
begin
  ModelsPage := CreateInputFilePage(
    wpSelectDir,
    'Select Models Archive',
    'Where is the models ZIP archive located?',
    'Select the Contour VFX models ZIP (made by scripts\build_models_zip.py). Only files under models\ are installed. Leave blank to skip and download the models later.'
  );
  ModelsPage.Add('Models Archive (*.zip)', 'ZIP Files|*.zip|All Files|*.*', '.zip');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ZipPath: string;
  DestPath: string;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    ZipPath := ModelsPage.Values[0];
    if (ZipPath <> '') and FileExists(ZipPath) then
    begin
      DestPath := ExpandConstant('{app}');
      ForceDirectories(DestPath);
      WizardForm.StatusLabel.Caption := 'Extracting models (this may take a while)...';
      // Only model data under models/ is extracted: no code, no path tricks, size-capped.
      ExtractTemporaryFile('extract_models.ps1');
      if not Exec('powershell.exe',
                  '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\extract_models.ps1') +
                  '" -Zip "' + ZipPath + '" -Dest "' + DestPath + '"',
                  '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
        MsgBox('The models archive could not be installed (code ' + IntToStr(ResultCode) + '). ' +
               'You can import it later from Settings > AI models.', mbError, MB_OK);
    end;
  end;
end;
