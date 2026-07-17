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
; Signing is configured by build.sh (/DSIGN plus an /Ssigntool= command)
; once a certificate exists; with SignTool set, Inno also signs the
; uninstaller. Without /DSIGN this compiles identically to an unsigned
; build.
#ifdef SIGN
SignTool=signtool
#endif
OutputDir=.
OutputBaseFilename=ia-helper-{#VERSION}-windows-x64-setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; Inno's default upgrade behavior only adds/overwrites files listed in
; [Files] — it never removes something the PREVIOUS version installed
; but the new one doesn't ship. For a PyInstaller bundle whose exact
; file manifest can change release to release (discovered 2026-07-17:
; trimming unused typelibs left 58 stale files behind on an in-place
; upgrade, since the installer had no way to know they were gone),
; wiping {app} first guarantees the installed tree always matches the
; current build exactly, with no versioned-away cruft accumulating.
[InstallDelete]
Type: filesandordirs; Name: "{app}"

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
