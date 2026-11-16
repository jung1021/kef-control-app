; KEF Control installer (per-user, no admin rights needed)
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"

!define APPNAME   "KEF Control"
!define VERSION   "1.3.2"
!define EXE       "KEFControl.exe"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\KEFControl"
!define RUNKEY    "Software\Microsoft\Windows\CurrentVersion\Run"

Name "${APPNAME}"
OutFile "KEFControl-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\KEF Control"
InstallDirRegKey HKCU "${UNINSTKEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${APPNAME} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Unofficial app, not affiliated with KEF"

!define MUI_ICON "..\src\kef_control.ico"
!define MUI_UNICON "..\src\kef_control.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "This will install ${APPNAME} ${VERSION}, a desktop app for controlling KEF wireless speakers (LSX II LT, LSX II, LS50 Wireless II, LS60, XIO).$\r$\n$\r$\nYour speakers need to be on your home network. Set up Wi-Fi once in KEF Connect if you haven't already.$\r$\n$\r$\nNo administrator rights are needed."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Open ${APPNAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; Stop a running copy (installed or the older install.bat version) so files can be replaced.
; Remove a folder, retrying while files are still being released.
!macro RemoveDirRetry DIR
  StrCpy $R9 0
  ${Do}
    RMDir /r "${DIR}"
    ${IfNot} ${FileExists} "${DIR}\*.*"
      ${Break}
    ${EndIf}
    IntOp $R9 $R9 + 1
    ${If} $R9 > 10
      ${Break}
    ${EndIf}
    Sleep 500
  ${Loop}
!macroend

!macro StopRunning
  ${If} ${FileExists} "$INSTDIR\${EXE}"
    ExecWait '"$INSTDIR\${EXE}" --quit'
  ${EndIf}
  ; Fallback for an older copy started some other way: ask it over its local port.
  nsExec::Exec 'powershell -NoProfile -NonInteractive -Command "try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri http://127.0.0.1:47801/api/quit -TimeoutSec 2 | Out-Null; Start-Sleep -Seconds 2 } catch {}"'
  Pop $0
!macroend

Section "${APPNAME} (required)" SecMain
  SectionIn RO
  !insertmacro StopRunning

  ; Fresh copy of the program files (settings in %APPDATA%\KEFControl are kept)
  !insertmacro RemoveDirRetry "$INSTDIR\runtime"
  !insertmacro RemoveDirRetry "$INSTDIR\app"
  SetOutPath "$INSTDIR"
  File "stage\${EXE}"
  File "/oname=kef_control.ico" "..\src\kef_control.ico"
  SetOutPath "$INSTDIR\app"
  File /r "stage\app\*.*"
  SetOutPath "$INSTDIR\runtime"
  File /r "stage\runtime\*.*"
  SetOutPath "$INSTDIR"

  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayName"     "${APPNAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "Publisher"       "KEF Control (unofficial)"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\${EXE}"
  WriteRegStr   HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr   HKCU "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" 46000
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
SectionEnd

Section "Start with Windows (tray icon)" SecStartup
  WriteRegStr HKCU "${RUNKEY}" "${APPNAME}" '"$INSTDIR\${EXE}" --background'
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain}    "The app, with its own private runtime. Nothing else needs to be installed."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Put a KEF Control icon on the desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartup} "Start in the taskbar's hidden-icons area when you sign in. You can change this later from the tray icon menu."
!insertmacro MUI_FUNCTION_DESCRIPTION_END


Function .onInstSuccess
  ${IfNot} ${SectionIsSelected} ${SecStartup}
    DeleteRegValue HKCU "${RUNKEY}" "${APPNAME}"
  ${EndIf}
FunctionEnd

Section "Uninstall"
  ${If} ${FileExists} "$INSTDIR\${EXE}"
    ExecWait '"$INSTDIR\${EXE}" --quit'
  ${EndIf}
  DeleteRegValue HKCU "${RUNKEY}" "${APPNAME}"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$DESKTOP\${APPNAME}.lnk"
  !insertmacro RemoveDirRetry "$INSTDIR\runtime"
  !insertmacro RemoveDirRetry "$INSTDIR\app"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\kef_control.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
  ; Your speaker address is kept in %APPDATA%\KEFControl in case you reinstall.
SectionEnd
