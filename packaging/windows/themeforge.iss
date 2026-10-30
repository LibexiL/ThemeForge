; Inno Setup script for the Windows installer. Built by packaging\windows\build.ps1 (and the release workflow):
;   ISCC.exe /DAppVersion=2.5.0 packaging\windows\themeforge.iss
; Installs per user (no admin prompt) into %LOCALAPPDATA%\Programs\ThemeForge. ThemeForge's built-in updater
; downloads a newer ThemeForge-Setup.exe and runs it with /SILENT; the [Run] entry opens the app again after.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{5B0E1D9A-7C2F-4E4B-9F3A-2D6C8E1A7B40}
AppName=ThemeForge
AppVersion={#AppVersion}
AppVerName=ThemeForge {#AppVersion}
AppPublisher=LibexiL
AppPublisherURL=https://github.com/LibexiL/ThemeForge
AppSupportURL=https://github.com/LibexiL/ThemeForge/issues
AppUpdatesURL=https://github.com/LibexiL/ThemeForge/releases
DefaultDirName={localappdata}\Programs\ThemeForge
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=ThemeForge-Setup
SetupIconFile=themeforge.ico
UninstallDisplayIcon={app}\ThemeForge.exe
UninstallDisplayName=ThemeForge
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an update replaces the bundled libraries completely, so nothing stale is left behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\ThemeForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\ThemeForge"; Filename: "{app}\ThemeForge.exe"
Name: "{userdesktop}\ThemeForge"; Filename: "{app}\ThemeForge.exe"; Tasks: desktopicon

[Registry]
; ThemeForge adds this itself when something is set to start at login; remove it on uninstall
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "ThemeForge"; ValueType: none; Flags: uninsdeletevalue

[Run]
Filename: "{app}\ThemeForge.exe"; Description: "{cm:LaunchProgram,ThemeForge}"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ThemeForge.exe"; Flags: runhidden; RunOnceId: "StopThemeForge"

[UninstallDelete]
Type: files; Name: "{userprograms}\ThemeForge Next Profile.lnk"
