; ============================================================================
;  All Clear Server Services™ — Inno Setup Installer Script
;  Requires Inno Setup 6.x — compile with:
;    & "C:\Program Files (x86)\Inno Setup 6\iscc.exe" AllClearServerServices_Setup.iss
;
;  Files expected next to this .iss:
;    splash_banner.bmp         — installer left-panel banner (164x314 BMP)
;    LICENSE.txt               — licence text shown on agreement page
;    dist\main\main.exe        — PyInstaller onedir output (executable)
;    dist\main\*               — all other PyInstaller runtime files
;    splash.png                — bundled with the app for runtime splash
; ============================================================================

#define AppName      "All Clear Server Services"
#define AppVersion   "1.0.0"
#define AppPublisher "All Clear Server Services LLC"
#define AppURL       "https://www.allclearserverservices.com"
#define AppExeName   "main.exe"
#define AppCopyright "Copyright (C) 2026 All Clear Server Services LLC"

[Setup]
AppId                     = {{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName                   = {#AppName}
AppVersion                = {#AppVersion}
AppVerName                = {#AppName} v{#AppVersion}
AppPublisher              = {#AppPublisher}
AppPublisherURL           = {#AppURL}
AppSupportURL             = {#AppURL}/support
AppUpdatesURL             = {#AppURL}/updates
AppCopyright              = {#AppCopyright}

VersionInfoVersion        = {#AppVersion}.0
VersionInfoCompany        = {#AppPublisher}
VersionInfoDescription    = {#AppName} Installer
VersionInfoCopyright      = {#AppCopyright}
VersionInfoProductName    = {#AppName}
VersionInfoProductVersion = {#AppVersion}

DefaultDirName            = {autopf}\{#AppName}
DefaultGroupName          = {#AppName}
OutputDir                 = installer_output
OutputBaseFilename        = AllClearServerServices_v{#AppVersion}_Setup

WizardImageFile           = splash_banner.bmp
WizardImageStretch        = yes
WizardStyle               = modern
WizardSizePercent         = 110

LicenseFile               = LICENSE.txt

Compression               = lzma2/ultra64
SolidCompression          = yes
InternalCompressLevel     = ultra

PrivilegesRequired        = admin
PrivilegesRequiredOverridesAllowed = commandline

AllowNoIcons              = yes
UninstallDisplayIcon      = {app}\{#AppExeName}
UninstallDisplayName      = {#AppName} v{#AppVersion}
ShowLanguageDialog        = auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full";    Description: "Full installation"
Name: "compact"; Description: "Compact installation (no desktop shortcut)"
Name: "custom";  Description: "Custom installation"; Flags: iscustom

[Components]
Name: "main";    Description: "Application files (required)"; Types: full compact custom; Flags: fixed
Name: "desktop"; Description: "Desktop shortcut";             Types: full

[Tasks]
Name: "launchapp";   Description: "&Launch {#AppName} after installation"; \
                     GroupDescription: "Additional options:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
                     GroupDescription: "Additional options:"; Components: desktop

; ── KEY FIX: paths now match PyInstaller onedir output at dist\main\ ─────────
[Files]
Source: "dist\main\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "dist\main\*";             DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "splash.png";              DestDir: "{app}"; Flags: ignoreversion; Components: main

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";     Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent; \
    Tasks: launchapp

[UninstallRun]
Filename: "{cmd}"; \
    Parameters: "/C taskkill /F /IM {#AppExeName} 2>nul"; \
    Flags: runhidden; RunOnceId: "KillApp"

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; \
    ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; \
    ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsWin64 then begin
    MsgBox('This application requires a 64-bit edition of Windows 10 or later.', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;
  if GetWindowsVersion < $0A000000 then begin
    MsgBox('This application requires Windows 10 or later.', mbCriticalError, MB_OK);
    Result := False;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := MsgBox(
    'Are you sure you want to completely remove {#AppName} and all of its components?',
    mbConfirmation, MB_YESNO) = idYes;
end;
