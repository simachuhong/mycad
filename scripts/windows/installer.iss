; SPDX-FileCopyrightText: 2026 MyCAD contributors
; SPDX-License-Identifier: Apache-2.0
#if VER < EncodeVer(6,5,0)
  #error Inno Setup compiler engine 6.5 or newer is required
#endif
#ifndef SourceDir
  #error SourceDir must be the absolute PyInstaller output directory
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif

[Setup]
AppId={{D2CF3854-9EE0-43CE-8B72-779D88DA685E}
AppName=MyCAD
AppVersion={#AppVersion}
AppPublisher=MyCAD contributors
AppPublisherURL=https://gitee.com/mark-sima/my-cad
DefaultDirName={localappdata}\Programs\MyCAD
DefaultGroupName=MyCAD
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=MyCAD-{#AppVersion}-x64-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
#ifdef IconPath
SetupIconFile={#IconPath}
#endif
SetupLogging=yes
UninstallLogging=yes
UninstallDisplayIcon={app}\MyCAD.exe
LicenseFile={#SourceDir}\_internal\release\LICENSE
CloseApplications=no
RestartApplications=no
AppMutex=MyCAD.Desktop.Running
SetupMutex=MyCAD.Setup.Running
ChangesAssociations=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked
Name: "fileassociation"; Description: "关联 MyCAD 二维和三维文档（.my2d / .my3d）"; Flags: unchecked

[InstallDelete]
; Only the frozen dependency directory is replaced. User data must never live here.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MyCAD"; Filename: "{app}\MyCAD.exe"; WorkingDir: "{userdocs}"
Name: "{group}\卸载 MyCAD"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MyCAD"; Filename: "{app}\MyCAD.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon

[Registry]
; OpenWith advertises our own ProgID; do not override an existing default application.
Root: HKCU; Subkey: "Software\Classes\.my2d\OpenWithProgids"; ValueType: none; ValueName: "MyCAD.Document"; Flags: uninsdeletevalue; Tasks: fileassociation
Root: HKCU; Subkey: "Software\Classes\.my3d\OpenWithProgids"; ValueType: none; ValueName: "MyCAD.Document"; Flags: uninsdeletevalue; Tasks: fileassociation
Root: HKCU; Subkey: "Software\Classes\MyCAD.Document"; ValueType: string; ValueData: "MyCAD 文档"; Flags: uninsdeletekey; Tasks: fileassociation
Root: HKCU; Subkey: "Software\Classes\MyCAD.Document\DefaultIcon"; ValueType: string; ValueData: """{app}\MyCAD.exe"",0"; Tasks: fileassociation
Root: HKCU; Subkey: "Software\Classes\MyCAD.Document\shell\open\command"; ValueType: string; ValueData: """{app}\MyCAD.exe"" ""%1"""; Tasks: fileassociation

[Run]
Filename: "{app}\MyCAD.exe"; Description: "启动 MyCAD"; WorkingDir: "{userdocs}"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExistingVersion: String;
  ExistingPacked, IncomingPacked: Int64;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}\_internal')) and
     not (FileExists(ExpandConstant('{app}\MyCAD.exe')) and
          FileExists(ExpandConstant('{app}\_internal\release\build-info.json'))) then
  begin
    Result := '所选目录包含非 MyCAD 的 _internal 文件夹，请选择其他安装目录。';
    Exit;
  end;
  if RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D2CF3854-9EE0-43CE-8B72-779D88DA685E}_is1',
      'DisplayVersion', ExistingVersion) then
    if StrToVersion(ExistingVersion, ExistingPacked) and
       StrToVersion('{#AppVersion}', IncomingPacked) then
      if ComparePackedVersion(ExistingPacked, IncomingPacked) > 0 then
        Result := '已安装更新的 MyCAD。请先卸载新版，再安装旧版。';
end;
