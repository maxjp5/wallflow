; Inno Setup script for Wallflow. Build with build.ps1 (it passes the version in).

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "Wallflow"
#define MyAppExe "Wallflow.exe"

[Setup]
AppId={{8C1E4F2A-6D3B-4B7E-9A51-3F0C2D7E9B14}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Wallflow
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=Wallflow-Setup-{#MyAppVersion}
SetupIconFile=wallflow.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\Wallflow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; Remove the "Start with Windows" entry when uninstalling (never creates it).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Wallflow"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch Wallflow"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Close Wallflow cleanly first (removes its tray icon), then make sure it's gone.
Filename: "{app}\{#MyAppExe}"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitWallflow"
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExe} /F"; Flags: runhidden; RunOnceId: "KillWallflow"

[Code]
// Before installing over a running copy, ask it to close cleanly so no ghost tray icon is left.
// Only when Wallflow is actually running, and never waits more than ~5 seconds.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code, I: Integer;
begin
  if CheckForMutexes('Wallflow_SingleInstance_Mutex') and FileExists(ExpandConstant('{app}\{#MyAppExe}')) then
  begin
    Exec(ExpandConstant('{app}\{#MyAppExe}'), '--quit', '', SW_HIDE, ewNoWait, Code);
    for I := 1 to 50 do
    begin
      if not CheckForMutexes('Wallflow_SingleInstance_Mutex') then Break;
      Sleep(100);
    end;
  end;
  Result := '';
end;
