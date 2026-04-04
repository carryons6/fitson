; Inno Setup script for AstroView
;
; Prerequisites:
;   1. Install Inno Setup: https://jrsoftware.org/isdl.php
;   2. Run PyInstaller first:  pyinstaller astroview.spec
;   3. Compile this script:    iscc installer.iss
;      or open in Inno Setup GUI and click Build -> Compile

#define MyAppName "AstroView"
#define MyAppVersion "1.2.5"
#define MyAppPublisher "Fitson"
#define MyAppExeName "AstroView.exe"

[Setup]
AppId={{A3B7C9E1-5F2D-4A8B-9C6E-7D1F0E2B3A4C}
AppName={#MyAppName}
AppVerName={#MyAppName} {#MyAppVersion}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=AstroView_Setup_{#MyAppVersion}
SetupIconFile=resources\icons\main_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#MyAppVersion}
UsePreviousAppDir=yes
UsePreviousTasks=yes
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\AstroView\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCR; Subkey: ".fits"; ValueType: string; ValueName: ""; ValueData: "AstroView.FITS"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCR; Subkey: ".FITS"; ValueType: string; ValueName: ""; ValueData: "AstroView.FITS"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCR; Subkey: ".fit"; ValueType: string; ValueName: ""; ValueData: "AstroView.FITS"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCR; Subkey: ".fts"; ValueType: string; ValueName: ""; ValueData: "AstroView.FITS"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCR; Subkey: "AstroView.FITS"; ValueType: string; ValueName: ""; ValueData: "FITS Image File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "AstroView.FITS\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey
Root: HKCR; Subkey: "AstroView.FITS\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey
