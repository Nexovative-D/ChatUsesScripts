; ============================================================
;  Nexovative Control Center - Setup Script
;  Compile this with Inno Setup (www.jrsoftware.org/isinfo.php)
;  to produce a single distributable setup.exe.
;
;  Output: a "Next > Next > Install" wizard that:
;    - copies the app files
;    - runs bootstrap.ps1 completely hidden (no PowerShell window ever
;      appears) while driving Inno's own progress bar from the
;      percentages bootstrap.ps1 writes to a progress file
;    - creates Start Menu / Desktop shortcuts
; ============================================================

#define MyAppName "Nexovative Control Center"
#define MyAppVersion "31.5.0"
#define MyAppPublisher "Nexovative"
#define MyAppExeName "Launch_NexovativeControlCenter.bat"

[Setup]
AppId={{8C6F2B2E-6B0B-4C7A-9C7A-NEXOVATIVE315}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Nexovative\ControlCenter
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
; admin is needed only for the VirtualBox silent install step; the app
; itself is intentionally run WITHOUT elevation later (see README).
WizardStyle=modern
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\app_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "files\NexovativeControlCenter.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "files\requirements.txt";                  DestDir: "{app}"; Flags: ignoreversion
Source: "files\bootstrap.ps1";                      DestDir: "{app}"; Flags: ignoreversion
Source: "files\Launch_NexovativeControlCenter.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "app_icon.ico";                             DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";               Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\Uninstall {#MyAppName}";     Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";         Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Launch {#MyAppName} now"; \
    Flags: nowait postinstall skipifsilent shellexec

[Code]
{ ============================================================
  Runs bootstrap.ps1 completely hidden (no console window, ever)
  and drives Inno's own progress bar from the percentages the
  script writes to a small progress file, so the user only ever
  sees the setup.exe wizard.

  Uses Inno's built-in Exec() with ewNoWait + SW_HIDE - both are
  provided natively by Inno Setup's Pascal Script, so this avoids
  declaring any raw Win32 structs. (An earlier version tried
  ShellExecuteEx with a hand-declared TShellExecuteInfo record and
  a redeclared SW_HIDE constant - both failed to compile, since
  SW_HIDE is already predefined by Inno and TShellExecuteInfo isn't
  a type Inno's Pascal Script provides.)
  ============================================================ }

var
  ProgressFile: String;
  BootstrapFailed: Boolean;
  BootstrapFailMsg: String;

{ Reads "PERCENT|MESSAGE" out of the progress file. Returns False if the
  file doesn't exist yet or can't be parsed (e.g. mid-write); caller just
  keeps the previous displayed value in that case. }
function TryReadProgress(var Percent: Integer; var Msg: String): Boolean;
var
  Lines: TArrayOfString;
  RawLine: String;
  SepPos: Integer;
begin
  Result := False;
  if not FileExists(ProgressFile) then Exit;
  if not LoadStringsFromFile(ProgressFile, Lines) then Exit;
  if GetArrayLength(Lines) = 0 then Exit;

  RawLine := Lines[0];
  SepPos := Pos('|', RawLine);
  if SepPos = 0 then Exit;

  Percent := StrToIntDef(Copy(RawLine, 1, SepPos - 1), -999);
  Msg := Copy(RawLine, SepPos + 1, Length(RawLine));
  if Percent = -999 then
  begin
    Result := False;
    Exit;
  end;
  Result := True;
end;

procedure RunBootstrapHiddenWithProgress();
var
  PSPath, ScriptPath, Params: String;
  Percent, LastPercent: Integer;
  Msg: String;
  ResultCode: Integer;
  ElapsedMs, TimeoutMs: Integer;
begin
  BootstrapFailed := False;
  BootstrapFailMsg := '';
  LastPercent := -1;
  ElapsedMs := 0;
  TimeoutMs := 30 * 60 * 1000; { 30 minutes - generous for slow connections
                                  downloading Python + VirtualBox, but still
                                  guarantees the wizard can't hang forever
                                  if bootstrap.ps1 crashes without writing
                                  a final status. }

  ProgressFile := ExpandConstant('{tmp}\Nexovative_Progress.txt');
  if FileExists(ProgressFile) then
    DeleteFile(ProgressFile);

  ScriptPath := ExpandConstant('{app}\bootstrap.ps1');
  PSPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Params := '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass ' +
            '-File "' + ScriptPath + '" -ProgressFile "' + ProgressFile + '"';

  WizardForm.StatusLabel.Caption := 'Preparing to download components...';
  WizardForm.ProgressGauge.Style := npbstNormal;
  WizardForm.ProgressGauge.Min := 0;
  WizardForm.ProgressGauge.Max := 100;
  WizardForm.ProgressGauge.Position := 0;

  { ewNoWait launches bootstrap.ps1 and returns immediately, so we can
    poll the progress file ourselves in the loop below. SW_HIDE keeps
    the PowerShell console window from ever appearing - Exec launches
    it hidden directly, no separate window-hiding trick needed. }
  if not Exec(PSPath, Params, '', SW_HIDE, ewNoWait, ResultCode) then
  begin
    BootstrapFailed := True;
    BootstrapFailMsg := 'Could not launch the setup helper process (error code ' + IntToStr(ResultCode) + ').';
    Exit;
  end;

  { Poll the progress file while the hidden process runs, updating the
    wizard's own progress bar and status text in real time. We detect
    completion by the progress file itself reaching 100 or -1 (failure),
    since ewNoWait doesn't hand us a waitable process handle. A timeout
    guards against the rare case where bootstrap.ps1 dies without ever
    writing a final status line. }
  while (LastPercent < 100) and (not BootstrapFailed) and (ElapsedMs < TimeoutMs) do
  begin
    if TryReadProgress(Percent, Msg) then
    begin
      if Percent = -1 then
      begin
        BootstrapFailed := True;
        BootstrapFailMsg := Msg;
      end
      else if Percent <> LastPercent then
      begin
        WizardForm.ProgressGauge.Position := Percent;
        WizardForm.StatusLabel.Caption := Msg;
        LastPercent := Percent;
      end;
    end;

    { NOTE: Inno Setup's Pascal Script has no Application.ProcessMessages
      (that's VCL/Delphi-only) - an earlier version called it here and
      failed to compile ("Unknown identifier 'Application'"). Inno's own
      built-in Sleep() already pumps the window's message queue as a side
      effect while it waits, which is what keeps the wizard responsive -
      this is the same pattern Inno's own examples use for polling loops
      like this one. So just sleeping in small steps is enough; no extra
      call is needed. }
    Sleep(100);
    ElapsedMs := ElapsedMs + 100;
  end;

  if (LastPercent < 100) and (not BootstrapFailed) then
  begin
    BootstrapFailed := True;
    BootstrapFailMsg := 'Setup timed out waiting for components to finish installing. ' +
                         'This can happen on a very slow connection - check %TEMP%\Nexovative_Install.log for details.';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RunBootstrapHiddenWithProgress();

    if BootstrapFailed then
    begin
      MsgBox('Setup finished copying files, but a required component failed to install:' + #13#10 + #13#10 +
             BootstrapFailMsg + #13#10 + #13#10 +
             'Details were logged to %TEMP%\Nexovative_Install.log. ' +
             'You can re-run this setup to retry, or check the log for what to fix manually.',
             mbError, MB_OK);
    end;
  end;
end;
