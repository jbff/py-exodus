; Inno Setup script for the py-exodus Windows installer.
; Built by .github/workflows/release.yml:
;   ISCC /DAppVersion=1.0.0b2 /DSourceDir=dist\py-exodus /DOutputDir=out packaging\windows\py-exodus.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\py-exodus"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
AppId={{6C1E3F2A-7B44-4E0B-9C5D-3E8A1D2F9B70}
AppName=py-exodus
AppVersion={#AppVersion}
AppPublisher=py-exodus
AppPublisherURL=https://github.com/jbff/py-exodus
DefaultDirName={autopf}\py-exodus
DefaultGroupName=py-exodus
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename=py-exodus-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\py-exodus.exe
LicenseFile={#SourceDir}\_internal\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\py-exodus"; Filename: "{app}\py-exodus.exe"
Name: "{group}\Uninstall py-exodus"; Filename: "{uninstallexe}"
Name: "{autodesktop}\py-exodus"; Filename: "{app}\py-exodus.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\py-exodus.exe"; Description: "{cm:LaunchProgram,py-exodus}"; Flags: nowait postinstall skipifsilent
