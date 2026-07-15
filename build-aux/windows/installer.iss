; Inno Setup script for IA Helper (per-user: no admin prompt, installs to
; %LOCALAPPDATA%\Programs). Build via build.sh, which passes VERSION and
; DISTDIR (the PyInstaller output, e.g. dist2):
;   ISCC.exe /DVERSION=1.3.1 /DDISTDIR=dist2 installer.iss

#ifndef VERSION
  #define VERSION "0.0.0"
#endif
#ifndef DISTDIR
  #define DISTDIR "dist"
#endif

[Setup]
AppId=io.github.stargazernz.IAHelper
AppName=IA Helper
AppVersion={#VERSION}
AppPublisher=Joe Hallmark
AppPublisherURL=https://github.com/stargazerNZ/ia_helper
AppSupportURL=https://github.com/stargazerNZ/ia_helper/issues
WizardStyle=modern
PrivilegesRequired=lowest
DefaultDirName={autopf}\IA Helper
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
SetupIconFile=ia-helper.ico
UninstallDisplayIcon={app}\ia-helper.exe
Compression=lzma2/max
SolidCompression=yes
OutputDir=.
OutputBaseFilename=ia-helper-{#VERSION}-windows-x64-setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DISTDIR}\ia-helper\*"; DestDir: "{app}"; \
    Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\IA Helper"; Filename: "{app}\ia-helper.exe"
Name: "{autodesktop}\IA Helper"; Filename: "{app}\ia-helper.exe"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\ia-helper.exe"; Description: "{cm:LaunchProgram,IA Helper}"; \
    Flags: nowait postinstall skipifsilent

; User data (config, download queue, cache in %APPDATA%/%LOCALAPPDATA%
; ia-helper dirs) is deliberately not touched on uninstall.
