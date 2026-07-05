; Local Flight - Windows Inno Setup installer
;
; Compile with:
;   python scripts/package_windows_installer.py
;
; The script passes AppVersion, SourceDir, and OutputDir. Defaults below make
; direct ISCC runs from this file work after python build.py has produced
; dist\LocalFlight.

#ifndef AppVersion
<<<<<<< HEAD
#define AppVersion "0.5.1"
=======
#define AppVersion "0.2.8"
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae
#endif

#ifndef SourceDir
#define SourceDir "..\..\dist\LocalFlight"
#endif

#ifndef OutputDir
#define OutputDir "..\..\dist"
#endif

#ifndef WizardImageFile
#define WizardImageFile "..\..\build\windows-installer-branding\wizard-image.bmp"
#endif

#ifndef WizardSmallImageFile
#define WizardSmallImageFile "..\..\build\windows-installer-branding\wizard-small.bmp"
#endif

#define AppName "Local Flight"
#define AppExeName "LocalFlight.exe"
#define AppPublisher "Beacon Tools"

[Setup]
AppId={{0D9DD1C7-E53C-4F7C-8D79-5E4D4522E66D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://beacontools.cc/local-flight
AppSupportURL=https://beacontools.cc/support
AppUpdatesURL=https://github.com/tr3y4rch/local-flight/releases
AppContact=privacy@beacontools.cc
AppCopyright=MIT License - Philipp Schumacher
DefaultDirName={localappdata}\Programs\Local Flight
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=LocalFlight-{#AppVersion}-Setup
SetupIconFile=..\..\assets\icon.ico
WizardImageFile={#WizardImageFile}
WizardSmallImageFile={#WizardSmallImageFile}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#AppExeName}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
