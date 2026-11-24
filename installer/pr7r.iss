; Paragon PR7-R installer (Inno Setup 6).
;   iscc /DAppVersion=0.1.0 installer\pr7r.iss      (after pyinstaller pr7r.spec has made dist\PR7-R)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-R, with a Start menu entry; ticked by default,
; PR7-R registers as a PDF reader: under "Open with" for PDFs and in Settings > Default apps (PR7-R --register, so
; installer and Options share shell.py). Windows doesn't let a program make itself the default: Options opens
; Default apps for that one click. --unregister on uninstall. History, favorites and settings stay.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{1BC53F2C-70E7-45EA-B97E-FC9294E87FC3}
AppName=Paragon PR7-R
AppVersion={#AppVersion}
AppVerName=Paragon PR7-R {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-R
DefaultGroupName=Paragon PR7-R
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-R-Setup-{#AppVersion}
SetupIconFile=..\pr7r\icons\app.ico
UninstallDisplayIcon={app}\PR7-R.exe
UninstallDisplayName=Paragon PR7-R
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "pdfreader"; Description: "Register PR7-R as a PDF reader (Open with, Default apps)"; GroupDescription: "Windows:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-R\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-R"; Filename: "{app}\PR7-R.exe"; Comment: "PDF reader"
Name: "{autodesktop}\Paragon PR7-R"; Filename: "{app}\PR7-R.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-R.exe"; Parameters: "--register"; Flags: runhidden waituntilterminated; Tasks: pdfreader
Filename: "{app}\PR7-R.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; Tasks: not pdfreader
Filename: "{app}\PR7-R.exe"; Description: "{cm:LaunchProgram,Paragon PR7-R}"; Flags: nowait postinstall skipifsilent
; Updates (Check for Updates runs this installer with /SILENT /relaunch=1): start PR7-R again when done.
Filename: "{app}\PR7-R.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[UninstallRun]
Filename: "{app}\PR7-R.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
