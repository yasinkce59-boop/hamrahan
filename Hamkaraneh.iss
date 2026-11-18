#define MyAppName "همکارانه"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "یاسین تقوی"
#define MyAppExeName "Hamkaraneh.exe"

[Setup]
AppId={{6E0C8D3A-5B7F-4C1E-9A52-3F1D7B2C84E1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Hamkaraneh
DefaultGroupName={#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
OutputDir=output
OutputBaseFilename=Hamkaraneh-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
AppMutex=HamkaranehAppMutex
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\Hamkaraneh\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
; Let the app talk to other computers on the same network (automatic, nothing to click).
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""Hamkaraneh"""; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""Hamkaraneh"" dir=in action=allow program=""{app}\{#MyAppExeName}"" enable=yes profile=any remoteip=localsubnet"; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "Open Hamkaraneh"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""Hamkaraneh"""; Flags: runhidden; RunOnceId: "DelFirewallRule"
