; NSIS installer for IA Helper (per-user: no admin prompt, installs to
; %LOCALAPPDATA%\Programs). Build via build.sh, which passes VERSION and
; stages the PyInstaller output at dist\ia-helper.

!define APPNAME "IA Helper"
!define APPID "io.github.stargazernz.IAHelper"
!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef DISTDIR
  !define DISTDIR "dist"
!endif

Name "${APPNAME} ${VERSION}"
OutFile "ia-helper-${VERSION}-windows-x64-setup.exe"
Unicode true
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\IA Helper"
SetCompressor /SOLID lzma

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${DISTDIR}\ia-helper\*.*"

  CreateDirectory "$SMPROGRAMS\IA Helper"
  CreateShortcut "$SMPROGRAMS\IA Helper\IA Helper.lnk" "$INSTDIR\ia-helper.exe"
  CreateShortcut "$SMPROGRAMS\IA Helper\Uninstall IA Helper.lnk" "$INSTDIR\uninstall.exe"

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Add/Remove Programs entry (per-user hive)
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "Publisher" "Joe Hallmark"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "URLInfoAbout" "https://github.com/stargazerNZ/ia_helper"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "DisplayIcon" "$INSTDIR\ia-helper.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" \
      "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; App files only — user data (config, download queue, cache) is kept.
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\IA Helper\IA Helper.lnk"
  Delete "$SMPROGRAMS\IA Helper\Uninstall IA Helper.lnk"
  RMDir "$SMPROGRAMS\IA Helper"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"
SectionEnd
