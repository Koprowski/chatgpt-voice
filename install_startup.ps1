# Create Startup shortcut: daemon (hidden, logs to file).
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
$LOG = Join-Path $env:LOCALAPPDATA "chatgpt-voice\daemon.log"
$LAUNCHER = Join-Path $DIR "start_daemon.ps1"

# Write a portable launcher script that runs the daemon hidden and logs all output.
$launcherContent = @'
$ErrorActionPreference = "Stop"

$DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PYTHON = Join-Path $DIR "venv\Scripts\python.exe"
$LOG = Join-Path $env:LOCALAPPDATA "chatgpt-voice\daemon.log"

$null = New-Item -Force -ItemType Directory (Split-Path $LOG)

if (-not (Test-Path $PYTHON)) {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Virtualenv python not found at $PYTHON" | Add-Content $LOG
    exit 1
}

Set-Location $DIR
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting chatgpt-voice daemon" | Add-Content $LOG
& $PYTHON -m chatgpt_voice start *>> $LOG
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Daemon exited (code $LASTEXITCODE)" | Add-Content $LOG
'@
[System.IO.File]::WriteAllText($LAUNCHER, $launcherContent + "`n", [System.Text.UTF8Encoding]::new($false))
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

# Remove legacy standalone visualizer startup shortcut. The daemon launches
# the visualizer with the same interpreter and working directory it uses.
$OldVisualizerShortcut = Join-Path $STARTUP "ChatGPT Voice Visualizer.lnk"
if (Test-Path $OldVisualizerShortcut) {
    Remove-Item $OldVisualizerShortcut
    Write-Host "Removed old: ChatGPT Voice Visualizer.lnk" -ForegroundColor Yellow
}

# 2. Start Menu shortcuts (for manual launch without rebooting)
$STARTMENU = Join-Path ([Environment]::GetFolderPath("Programs")) "ChatGPT Voice"
New-Item -ItemType Directory -Path $STARTMENU -Force | Out-Null

$smDaemon = $WScript.CreateShortcut((Join-Path $STARTMENU "ChatGPT Voice (Daemon).lnk"))
$smDaemon.TargetPath = "powershell.exe"
$smDaemon.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LAUNCHER`""
$smDaemon.WorkingDirectory = $DIR
$smDaemon.Description = "Launch ChatGPT Voice daemon (hidden, logs to $LOG)"
$smDaemon.Save()

$OldStartMenuVisualizer = Join-Path $STARTMENU "ChatGPT Voice Visualizer.lnk"
if (Test-Path $OldStartMenuVisualizer) {
    Remove-Item $OldStartMenuVisualizer
    Write-Host "Removed old Start Menu visualizer shortcut" -ForegroundColor Yellow
}

$smRestart = $WScript.CreateShortcut((Join-Path $STARTMENU "ChatGPT Voice (Restart).lnk"))
$smRestart.TargetPath = "powershell.exe"
$smRestart.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $DIR 'restart.ps1')`""
$smRestart.WorkingDirectory = $DIR
$smRestart.Description = "Kill and relaunch ChatGPT Voice daemon"
$smRestart.Save()

Write-Host "Created Start Menu shortcuts under 'ChatGPT Voice'" -ForegroundColor Green

# 3. Desktop control-panel shortcut (provider/settings/diagnostics)
& $PYTHON -m chatgpt_voice install-shortcuts | ForEach-Object {
    Write-Host "Created/updated shortcut: $_" -ForegroundColor Green
}

[System.Runtime.Interopservices.Marshal]::ReleaseComObject($WScript) | Out-Null

Write-Host ""
Write-Host "On login: daemon runs hidden and launches the visualizer helper." -ForegroundColor Cyan
Write-Host "When you press Ctrl+Shift+. and record, a small wave window appears." -ForegroundColor Cyan
Write-Host "Daemon log: $LOG" -ForegroundColor Cyan
Write-Host "To remove: delete the shortcuts from $STARTUP" -ForegroundColor Gray
