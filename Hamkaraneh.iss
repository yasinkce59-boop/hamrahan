#define MyAppName "همکارانه"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "یاسین تقوی"
#define MyAppExeName "Hamkaraneh.exe"

[Setup]
AppId={{F2B02EF4-3611-4AAD-93C7-7BC96F897C2A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Hamkaraneh
DefaultGroupName={#MyAppName}
OutputDir=output
OutputBaseFilename=Hamkaraneh-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "firewall"; Description: "ایجاد مجوز فایروال برای شبکه خصوصی (پورت 8000)"; Flags: unchecked
Name: "desktopicon"; Description: "ساخت میانبر روی دسکتاپ"; Flags: unchecked

[Files]
Source: "dist\Hamkaraneh\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{commonappdata}\Hamkaraneh"; Permissions: users-modify
Name: "{commonappdata}\Hamkaraneh\shared_files"; Permissions: users-modify

[Icons]
Name: "{group}\همکارانه - اجرای سرور"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\همکارانه - اجرای سرور"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "netsh"; Parameters: 'advfirewall firewall add rule name="Hamkaraneh LAN 8000" dir=in action=allow protocol=TCP localport=8000 profile=private'; Tasks: firewall; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "اجرای سرور همکارانه"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "netsh"; Parameters: 'advfirewall firewall delete rule name="Hamkaraneh LAN 8000"'; Flags: runhidden
