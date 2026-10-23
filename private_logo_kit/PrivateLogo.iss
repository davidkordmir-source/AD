#ifndef AppVersion
#define AppVersion "3.5.0"
#endif
#ifndef StageDir
#error StageDir is required
#endif
#ifndef OutputDir
#define OutputDir "..\dist"
#endif
[Setup]
AppId={{D76E40E5-9EDD-4C96-96F1-5A29C7C66123}
AppName=Fast Viewshed
AppVersion={#AppVersion}
AppPublisher=Fast Viewshed
DefaultDirName={localappdata}\Programs\FastViewshed
DefaultGroupName=Fast Viewshed
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutputDir}
OutputBaseFilename=FastViewshed_With_Logo_Setup
SetupIconFile={#StageDir}\assets\aircraft.ico
UninstallDisplayIcon={app}\FastViewshed.exe
Compression=none
SolidCompression=no
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
AppMutex=FastViewshed.Desktop.Running
MinVersion=10.0
SetupLogging=yes
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce
[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Fast Viewshed"; Filename: "{app}\FastViewshed.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\aircraft.ico"; AppUserModelID: "FastViewshed.Desktop"
Name: "{autodesktop}\Fast Viewshed"; Filename: "{app}\FastViewshed.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\aircraft.ico"; Tasks: desktopicon; AppUserModelID: "FastViewshed.Desktop"
Name: "{group}\Uninstall Fast Viewshed"; Filename: "{uninstallexe}"
[Run]
Filename: "{app}\FastViewshed.exe"; Description: "Open Fast Viewshed"; Flags: postinstall nowait skipifsilent
[InstallDelete]
Type: files; Name: "{app}\Branding\logo.png"
Type: files; Name: "{app}\Branding\logo.jpg"
Type: files; Name: "{app}\Branding\logo.jpeg"
Type: files; Name: "{app}\Branding\logo.bmp"
Type: files; Name: "{app}\Branding\logo.ico"
[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime_offline"
Type: files; Name: "{app}\OFFLINE_INSTALL.log"
Type: files; Name: "{app}\OFFLINE_CHECK.json"
Type: files; Name: "{app}\RUNTIME_READY.json"
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Parameters: String;
begin
  if CurStep = ssPostInstall then begin
    Parameters := '/d /s /c ""' + ExpandConstant('{app}\Install_Fast_Viewshed.bat') + '" --quiet"';
    if not Exec(ExpandConstant('{sys}\cmd.exe'), Parameters, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException('Unable to initialize the bundled offline runtime.');
    if ExitCode <> 0 then
      RaiseException('Offline initialization failed. See OFFLINE_INSTALL.log in the installation folder. No internet installation was attempted.');
  end;
end;
