# Create Startup shortcuts: daemon (hidden, logs to file) + recording visualizer.
# Run from the chatgpt-voice folder: powershell -ExecutionPolicy Bypass -File install_startup.ps1
# Uses this folder's venv (run from your install directory).

$ErrorActionPreference = "Stop"
$DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VENV = Join-Path $DIR "venv"
$PYTHON = Join-Path $VENV "Scripts\python.exe"
$PYTHONW = Join-Path $VENV "Scripts\pythonw.exe"

if (-not (Test-Path $PYTHON)) {
    Write-Host "Virtualenv not found at $VENV. Run setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$STARTUP = [Environment]::GetFolderPath("Startup")
$LOG = Join-Path $env:APPDATA "chatgpt-voice\daemon.log"
$LAUNCHER = Join-Path $DIR "start_daemon.ps1"

# Write a launcher script that runs the daemon hidden and logs all output.
@"
`$LOG = "$LOG"
`$null = New-Item -Force -ItemType Directory (Split-Path `$LOG)
"[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting chatgpt-voice daemon" | Add-Content `$LOG
& "$PYTHON" -m chatgpt_voice start *>> `$LOG
"[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Daemon exited (code `$LASTEXITCODE)" | Add-Content `$LOG
"@ | Set-Content $LAUNCHER -Encoding UTF8
Write-Host "Created: start_daemon.ps1" -ForegroundColor Green

# 1. Daemon: hidden PowerShell window, all output goes to log file.
$WScript = New-Object -ComObject WScript.Shell
$Shortcut = $WScript.CreateShortcut((Join-Path $STARTUP "ChatGPT Voice.lnk"))
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LAUNCHER`""
$Shortcut.WorkingDirectory = $DIR
$Shortcut.Description = "ChatGPT Voice daemon (logs to $LOG)"
$Shortcut.Save()
Write-Host "Created: ChatGPT Voice.lnk" -ForegroundColor Green

# Remove old terminal shortcut if present.
$OldShortcut = Join-Path $STARTUP "ChatGPT Voice (Terminal).lnk"
if (Test-Path $OldShortcut) {
    Remove-Item $OldShortcut
    Write-Host "Removed old: ChatGPT Voice (Terminal).lnk" -ForegroundColor Yellow
}

# 2. Recording visualizer (no terminal; small wave window only when recording)
$Shortcut2 = $WScript.CreateShortcut((Join-Path $STARTUP "ChatGPT Voice Visualizer.lnk"))
$Shortcut2.TargetPath = $PYTHONW
$Shortcut2.Arguments = "-m chatgpt_voice visualizer"
$Shortcut2.WorkingDirectory = $DIR
$Shortcut2.Description = "ChatGPT Voice recording indicator (wave when recording)"
$Shortcut2.Save()
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($WScript) | Out-Null
Write-Host "Created: ChatGPT Voice Visualizer.lnk" -ForegroundColor Green

Write-Host ""
Write-Host "On login: daemon runs hidden; visualizer shows a wave window when recording." -ForegroundColor Cyan
Write-Host "When you press Ctrl+Shift+. and record, a small wave window appears." -ForegroundColor Cyan
Write-Host "Daemon log: $LOG" -ForegroundColor Cyan
Write-Host "To remove: delete the shortcuts from $STARTUP" -ForegroundColor Gray
