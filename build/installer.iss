; Contour VFX installer (Inno Setup 6). Built by build\BUILD.bat; do not compile before
; build_app.py has made build\stage\ContourVFX and build\version.iss.
;
; Output: build\Output\ContourVFX_Setup_<version>.exe plus ContourVFX_Setup_<version>-1.bin,
; -2.bin, ... The payload (the app and its Python with PyTorch/CUDA) is bigger than the
; 2,097,152,000-byte limit Inno has for one setup file, so DiskSpanning splits it into .bin
; slices. Ship the exe and every .bin together, in one folder.
;
; The AI models (about 27 GB) are not inside: the last page offers to download them with
; download_models.bat (pinned, hash-checked, resumable), or they can be added later from the
; Start menu or from an offline models ZIP.

#include "version.iss"

[Setup]
; AppId must never change: Windows uses it to find this app for upgrades and uninstall.
AppId={{7C2E4B1A-5D3F-4E8A-9B61-0C4F2A7D93E5}
AppName=Contour VFX
AppVersion={#AppVersion}
AppVerName=Contour VFX {#AppVersion}
AppPublisher=Utkarsh Tripathi
AppPublisherURL=https://github.com/capsuleutkarsh-design/UTVFX_AI_VFX_Suit
AppSupportURL=https://github.com/capsuleutkarsh-design/UTVFX_AI_VFX_Suit/issues
; Per-user install: the app writes its settings, caches and models next to itself.
DefaultDirName={localappdata}\Programs\Contour VFX
PrivilegesRequired=lowest
DefaultGroupName=Contour VFX
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=Output
OutputBaseFilename=ContourVFX_Setup_{#AppVersion}
SetupIconFile=..\branding\app_icon.ico
UninstallDisplayIcon={app}\ContourVFX.exe
WizardImageFile=..\branding\wizard_large.bmp
WizardSmallImageFile=..\branding\wizard_small.bmp
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; About 6 GB for the app, plus room for the models it offers to download.
ExtraDiskSpaceRequired=29000000000
CloseApplications=yes

[Files]
Source: "extract_models.ps1"; Flags: dontcopy
Source: "stage\ContourVFX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\Contour VFX"; Filename: "{app}\ContourVFX.exe"; WorkingDir: "{app}"
Name: "{group}\Download AI models"; Filename: "{app}\download_models.bat"; WorkingDir: "{app}"; IconFilename: "{app}\ContourVFX.exe"
Name: "{group}\Third-party notices"; Filename: "{app}\THIRD_PARTY_NOTICES.md"
Name: "{group}\Uninstall Contour VFX"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Contour VFX"; Filename: "{app}\ContourVFX.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\download_models.bat"; WorkingDir: "{app}"; \
    Description: "Download the AI models now (about 27 GB; you can also do it later from the Start menu)"; \
    Flags: postinstall shellexec waituntilterminated skipifsilent
Filename: "{app}\ContourVFX.exe"; WorkingDir: "{app}"; Description: "Start Contour VFX"; \
    Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Made by the app while it runs, so the uninstaller would otherwise leave them.
Type: files; Name: "{app}\settings.json"
Type: files; Name: "{app}\crash.log"
Type: filesandordirs; Name: "{app}\.downloads"
; Python writes __pycache__ folders beside the installed code; take the whole trees.
Type: filesandordirs; Name: "{app}\python_base"
Type: filesandordirs; Name: "{app}\utvfx"

[Code]
var
  ModelsPage: TInputFileWizardPage;

procedure InitializeWizard;
begin
  ModelsPage := CreateInputFilePage(
    wpSelectDir,
    'Offline models (optional)',
    'Do you have a Contour VFX models ZIP?',
    'If you made a models ZIP on another computer (scripts\build_models_zip.py), select it to install ' +
    'the models from it. Only files under models\ are installed. Leave this blank to download the ' +
    'models instead.');
  ModelsPage.Add('Models archive (*.zip)', 'ZIP files|*.zip|All files|*.*', '.zip');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ZipPath: string;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    ZipPath := ModelsPage.Values[0];
    if (ZipPath <> '') and FileExists(ZipPath) then
    begin
      WizardForm.StatusLabel.Caption := 'Installing models from the ZIP (this can take a while)...';
      // Only model data under models/ is extracted: no code, no path tricks, size-capped.
      ExtractTemporaryFile('extract_models.ps1');
      if not Exec('powershell.exe',
                  '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\extract_models.ps1') +
                  '" -Zip "' + ZipPath + '" -Dest "' + ExpandConstant('{app}') + '"',
                  '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
        MsgBox('The models archive could not be installed (code ' + IntToStr(ResultCode) + '). ' +
               'You can download the models later from the Start menu (Download AI models).', mbError, MB_OK);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if DirExists(ExpandConstant('{app}\models')) or DirExists(ExpandConstant('{app}\workspace')) then
      if MsgBox('Also delete the downloaded AI models and your projects, caches and renders ' +
                '(the models and workspace folders)?' + #13#10#13#10 +
                'Choose No to keep them for a later install.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(ExpandConstant('{app}\models'), True, True, True);
        DelTree(ExpandConstant('{app}\workspace'), True, True, True);
        DelTree(ExpandConstant('{app}\plugins\3DTracker\bin'), True, True, True);
      end;
  end;
end;
