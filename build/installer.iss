; Contour VFX installer (Inno Setup 6). Built by build\BUILD.bat; do not compile before
; build_app.py has made build\stage\ContourVFX and build\version.iss.
;
; Output: build\Output\ContourVFX_Setup_<version>.exe plus ContourVFX_Setup_<version>-1.bin,
; -2.bin, ... The payload (the app and its Python with PyTorch/CUDA) is bigger than the
; 2,097,152,000-byte limit Inno has for one setup file, so DiskSpanning splits it into .bin
; slices. Ship the exe and every .bin together, in one folder.
;
; The AI models (about 27 GB) are not inside. For offline computers, "BUILD.bat models" makes
; ContourVFX_Models_<version>.zip.001, .002, ... and the "Offline models" page takes the .001:
; every file is installed and checked against its SHA-256. Otherwise the last page offers to
; download them (download_models.bat: pinned, hash-checked, resumable), also in the Start menu.

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
    Flags: postinstall shellexec waituntilterminated skipifsilent; Check: not OfflineModelsChosen
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
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
var
  ModelsPage: TInputFileWizardPage;

procedure InitializeWizard;
begin
  ModelsPage := CreateInputFilePage(
    wpSelectDir,
    'Offline models (optional)',
    'Install the AI models from an offline model pack?',
    'For computers without internet: select the first part of the model pack ' +
    '(ContourVFX_Models_<version>.zip.001). All the other parts must be in the same folder. ' +
    'Every file is checked after it is installed.' + #13#10#13#10 +
    'Leave this blank to download the models from the internet instead.');
  ModelsPage.Add('First part of the model pack (.001)', 'Model pack|*.001|All files|*.*', '.001');
end;

function OfflineModelsChosen: Boolean;
begin
  Result := (ModelsPage.Values[0] <> '') and FileExists(ModelsPage.Values[0]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = ModelsPage.ID) and (ModelsPage.Values[0] <> '') and not FileExists(ModelsPage.Values[0]) then
  begin
    MsgBox('That file does not exist. Select the .001 part of the model pack, or leave the box empty.',
           mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and OfflineModelsChosen then
  begin
    WizardForm.StatusLabel.Caption := 'Installing the AI models from the model pack (about 27 GB, a few minutes)...';
    // A console window shows the progress; each file is checked against the pack's SHA-256 list.
    if not Exec(ExpandConstant('{app}\python_base\python.exe'),
                '-u "' + ExpandConstant('{app}\scripts\install_models.py') + '" "' + ModelsPage.Values[0] + '"',
                ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      MsgBox('The models could not be installed from the pack (code ' + IntToStr(ResultCode) + '). ' +
             'Check that every part is in one folder, then run this in the install folder:' + #13#10 +
             'python_base\python.exe scripts\install_models.py <path to the .001 file>', mbError, MB_OK);
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
