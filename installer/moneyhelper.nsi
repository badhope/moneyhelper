; Moneyhelper Windows 安装包（NSIS 3）
;
; 设计要点：
; - 安装到 Program Files（每用户可选），卸载可从「应用和功能」正常移除；
; - 数据目录固定 %LOCALAPPDATA%\Moneyhelper，卸载默认保留（账本不能因卸载丢失）；
; - 开始菜单 + 桌面快捷方式，带图标；
; - 安装后检测端口占用：8788 被占则提示，不静默失败；
; - 不写系统 PATH、不改注册表全局项、不装服务。
;
; 构建：makensis -DVERSION=4.16.0 -DSRCEXE=..\backend\dist\moneyhelper.exe installer\moneyhelper.nsi

Unicode true

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef SRCEXE
  !define SRCEXE "..\backend\dist\moneyhelper.exe"
!endif

!define APPNAME "Moneyhelper"
!define COMPANY "Moneyhelper Contributors"
!define APPID "Moneyhelper"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"

Name "${APPNAME} ${VERSION}"
OutFile "..\backend\dist\Moneyhelper-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "Software\${APPID}" "InstallDir"
; 每用户安装：不请求管理员提权。安装器弹 UAC 会让静默安装卡住，
; 且桌面/开始菜单快捷方式本来就该是每用户的。
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "CompanyName" "${COMPANY}"
VIAddVersionKey "FileDescription" "${APPNAME} 安装程序"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "MIT License"

!include "MUI2.nsh"
!define MUI_ICON "..\backend\app.ico"
!define MUI_UNICON "..\backend\app.ico"
!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "主程序" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; 关键：先结束同名进程，否则覆盖 exe 会失败（Windows 文件锁）
  nsExec::ExecToLog 'taskkill /F /IM moneyhelper.exe'
  Pop $0
  Sleep 800

  File "${SRCEXE}"
  File "..\backend\app.ico"
  File "..\LICENSE"

  CreateDirectory "$LOCALAPPDATA\Moneyhelper"

  ; 快捷方式
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\moneyhelper.exe" "" "$INSTDIR\app.ico" 0
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\moneyhelper.exe" "" "$INSTDIR\app.ico" 0
  CreateShortcut "$SMPROGRAMS\${APPNAME}\卸载 ${APPNAME}.lnk" "$INSTDIR\uninstall.exe"

  ; 卸载信息（出现在「应用和功能」）
  WriteRegStr HKCU "Software\${APPID}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${COMPANY}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\app.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "启动 ${APPNAME}" SecRun
  ; 安装完直接启动（用户可在组件页取消）。
  ; 静默安装（/S，CI/批量部署）必须跳过：否则会占住端口、让安装进程挂住。
  IfSilent +2
  Exec '"$INSTDIR\moneyhelper.exe"'
SectionEnd

Section "Uninstall"
  nsExec::ExecToLog 'taskkill /F /IM moneyhelper.exe'
  Pop $0
  Sleep 800

  Delete "$INSTDIR\moneyhelper.exe"
  Delete "$INSTDIR\app.ico"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"

  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\卸载 ${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APPID}"

  ; 数据目录默认保留：账本是用户资产，卸载程序不应替用户决定删库。
  ; 需要彻底清除时在「设置 → 数据与状态」里手动删除，或删除下面这个目录。
  ; 静默卸载（/S）不能弹窗——MessageBox 在 silent 下仍会阻塞；默认保留数据（安全侧）。
  IfSilent keepdata
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "是否同时删除本地数据（账本、备份、配置）？$\r$\n$\r$\n位置：$LOCALAPPDATA\Moneyhelper$\r$\n$\r$\n选择「否」将保留数据，重新安装后可继续使用。" \
    IDNO keepdata
    RMDir /r "$LOCALAPPDATA\Moneyhelper"
  keepdata:
SectionEnd

Function .onInit
  ; 端口占用检查：8788 被占时给明确提示（不静默失败）。
  ; 静默安装跳过提示（部署脚本自己负责端口规划）。
  nsExec::ExecToStack 'cmd /c netstat -ano | findstr ":8788 " | findstr LISTENING'
  Pop $0
  Pop $1
  StrCmp $1 "" port_ok
    IfSilent port_ok
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "检测到 8788 端口已被占用。$\r$\n$\r$\nMoneyhelper 启动时会使用该端口，若被其他程序占用将无法访问。$\r$\n请先关闭占用该端口的程序，或在启动前设置环境变量 PORT 换一个端口。"
  port_ok:
FunctionEnd
