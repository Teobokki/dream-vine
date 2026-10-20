#define MyVer "1.4.0"
[Setup]
AppId={{7D1E5A92-3C4B-4F6E-A8D1-2B9C0E7F4A63}
AppName=DREAM VINE
AppVersion={#MyVer}
AppVerName=DREAM VINE {#MyVer}
AppPublisher=EX Inc./HYPERION DIGITAL
AppPublisherURL=https://github.com/Teobokki/dream-vine
AppCopyright=©2026 EX Inc./HYPERION DIGITAL ©2026
VersionInfoVersion={#MyVer}.0
VersionInfoCompany=EX Inc./HYPERION DIGITAL
VersionInfoCopyright=©2026 EX Inc./HYPERION DIGITAL ©2026
VersionInfoProductName=DREAM VINE
VersionInfoDescription=DREAM VINE Setup
DefaultDirName={localappdata}\Programs\DREAM VINE
DefaultGroupName=DREAM VINE
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=DREAM.VINE.Setup.{#MyVer}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\DREAM VINE.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\DREAM VINE\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DREAM VINE"; Filename: "{app}\DREAM VINE.exe"
Name: "{group}\Uninstall DREAM VINE"; Filename: "{uninstallexe}"
Name: "{userdesktop}\DREAM VINE"; Filename: "{app}\DREAM VINE.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DREAM VINE.exe"; Description: "Launch DREAM VINE now"; Flags: nowait postinstall skipifsilent
