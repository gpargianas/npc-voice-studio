#ifndef AppVersion
  #error AppVersion must be supplied by the release build.
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by the release build.
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by the release build.
#endif

#define AppName "NPC Voice Studio"
#define AppPublisher "NPC Voice Studio contributors"
#define AppExeName "NPC Voice Studio.exe"
#define OutputName "NPC-Voice-Studio-" + AppVersion + "-alpha-win-x64"

[Setup]
AppId={{E5F44C12-52D8-4FAB-8A5E-7AE53A7B066D}
AppName={#AppName}
AppVersion={#AppVersion} alpha
AppVerName={#AppName} {#AppVersion} alpha
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile={#SourceDir}\LICENSE
SetupIconFile={#SourceDir}\assets\app_icon.ico
UninstallDisplayIcon={app}\assets\app_icon.ico
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app_icon.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    MsgBox(
      'NPC Voice Studio application files were removed.' + #13#10 + #13#10 +
      'Your models, saved voices, generated audio, and logs remain in:' + #13#10 +
      ExpandConstant('{localappdata}\NPC Voice Studio'),
      mbInformation,
      MB_OK
    );
end;
