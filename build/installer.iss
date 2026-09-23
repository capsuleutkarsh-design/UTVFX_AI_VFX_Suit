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
Source: "..\dist\ContourVFX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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
    'Select the .zip file containing the ML models (e.g., sam3, vit_b). The installer will extract these into the app folder. You can leave it blank to skip.'
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
      // Use PowerShell to extract the zip silently
      Exec('powershell.exe', '-NoProfile -Command "Expand-Archive -Path ''' + ZipPath + ''' -DestinationPath ''' + DestPath + ''' -Force"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;
