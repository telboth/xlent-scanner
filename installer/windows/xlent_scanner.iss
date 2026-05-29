#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#ifndef SourceDir
  #define SourceDir "..\..\artifacts\windows\app\dist\XLENTScanner"
#endif

#ifndef OutputDir
  #define OutputDir "..\..\artifacts\windows\installer"
#endif

#define AppId "{{AE4DABFA-8FA9-40D5-9815-D9322B992A92}"
#define AppName "XLENT Compliance-scanner"
#define AppExeName "XLENTScanner.exe"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=xlent-scanner-setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Høyreklikk-kontekstmeny for alle filtyper
Root: HKCR; Subkey: "*\shell\XLENT Scanner";            ValueType: string; ValueData: "Skann med XLENT";                    Flags: uninsdeletekey
Root: HKCR; Subkey: "*\shell\XLENT Scanner";            ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName},0"
Root: HKCR; Subkey: "*\shell\XLENT Scanner\command";    ValueType: string; ValueData: """{app}\{#AppExeName}"" ""%1"""

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
