; StoCookie Inno Setup 安装脚本

[Setup]
AppName=StoCookie
AppVersion=1.0.0
AppPublisher=STO
DefaultDirName={autopf}\StoCookie
DefaultGroupName=StoCookie
OutputBaseFilename=StoCookie_Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=gui\resources\icon.ico
UninstallDisplayIcon={app}\StoCookie.exe

[Files]
; PyInstaller 打包输出
Source: "dist\StoCookie\*"; DestDir: "{app}"; Flags: recursesubdirs
; Chromium 浏览器
Source: "browsers\*"; DestDir: "{app}\browsers"; Flags: recursesubdirs

[Dirs]
Name: "{app}\storage"
Name: "{app}\logs"

[Icons]
Name: "{group}\StoCookie"; Filename: "{app}\StoCookie.exe"
Name: "{autodesktop}\StoCookie"; Filename: "{app}\StoCookie.exe"

[Registry]
; 开机自启
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "StoCookie"; ValueData: """{app}\StoCookie.exe"""; \
  Flags: uninsdeletevalue

[Run]
Filename: "{app}\StoCookie.exe"; Description: "启动 StoCookie"; Flags: nowait postinstall skipifsilent
