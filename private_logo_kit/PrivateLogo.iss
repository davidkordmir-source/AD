#ifndef KitRoot
#error KitRoot is required
#endif
#ifndef LogoFile
#error LogoFile is required
#endif
#ifndef OutputDir
#error OutputDir is required
#endif
#ifndef BaseSHA256
#error BaseSHA256 is required
#endif
[Setup]
AppId=FastViewshed.PrivateLogoBundle
AppName=Fast Viewshed
AppVersion=3.4.0
AppPublisher=Fast Viewshed
DefaultDirName={localappdata}\Programs\FastViewshed
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
Uninstallable=no
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir={#OutputDir}
OutputBaseFilename=FastViewshed_With_Logo_Setup
SetupIconFile={#KitRoot}\aircraft.ico
Compression=none
SolidCompression=no
WizardStyle=modern
MinVersion=10.0
AppMutex=FastViewshed.Desktop.Running
[Files]
Source: "{#KitRoot}\BaseSetup.exe"; Flags: dontcopy
Source: "{#KitRoot}\desktop_customization.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#KitRoot}\check_offline.py"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "{#KitRoot}\_Verify_Branding.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#LogoFile}"; DestDir: "{app}\Branding"; DestName: "logo.png"; Flags: ignoreversion
[Run]
Filename: "{app}\FastViewshed.exe"; Description: "Open Fast Viewshed"; Flags: postinstall nowait skipifsilent
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Parameters: String;
  LogFolder: String;
begin
  if CurStep = ssInstall then begin
    ExtractTemporaryFile('BaseSetup.exe');
    if GetSHA256OfFile(ExpandConstant('{tmp}\BaseSetup.exe')) <> '{#BaseSHA256}' then
      RaiseException('The embedded base installer failed SHA256 verification.');
    LogFolder := ExpandConstant('{localappdata}\FastViewshed\Logs');
    ForceDirectories(LogFolder);
    Parameters := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /TASKS="desktopicon" /DIR="' + ExpandConstant('{app}') + '" /LOG="' + LogFolder + '\BaseSetup.log"';
    if not Exec(ExpandConstant('{tmp}\BaseSetup.exe'), Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException('Unable to start the embedded offline installer.');
    if ExitCode <> 0 then
      RaiseException('Base installation failed. See ' + LogFolder + '\BaseSetup.log');
  end;
  if CurStep = ssPostInstall then begin
    Parameters := '/d /s /c ""' + ExpandConstant('{app}\_Verify_Branding.bat') + '""';
    if not Exec(ExpandConstant('{sys}\cmd.exe'), Parameters, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException('Unable to validate the installed branded application.');
    if ExitCode <> 0 then
      RaiseException('Branded application validation failed. See FastViewshed\Logs\BrandingCheck.log in LocalAppData.');
  end;
end;
