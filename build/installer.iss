[Setup]
AppName=UT_VFX_AI/VFX_Tool
AppVersion=1.0.0
DefaultDirName={autopf}\UT_VFX_Tool
DefaultGroupName=UT_VFX_Tool
OutputDir=..\Output
OutputBaseFilename=UT_VFX_Tool_Setup
SetupIconFile=app_icon.ico
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "..\dist\UTVFX_AI_VFX_Tool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\UT_VFX_AI VFX_Tool"; Filename: "{app}\UTVFX_AI_VFX_Tool.exe"; IconFilename: "{app}\UTVFX_AI_VFX_Tool.exe"
Name: "{autodesktop}\UT_VFX_AI VFX_Tool"; Filename: "{app}\UTVFX_AI_VFX_Tool.exe"; IconFilename: "{app}\UTVFX_AI_VFX_Tool.exe"; Tasks: desktopicon

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
      DestPath := ExpandConstant('{app}\models');
      ForceDirectories(DestPath);
      WizardForm.StatusLabel.Caption := 'Extracting models (this may take a while)...';
      // Use PowerShell to extract the zip silently
      Exec('powershell.exe', '-NoProfile -Command "Expand-Archive -Path ''' + ZipPath + ''' -DestinationPath ''' + DestPath + ''' -Force"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;
