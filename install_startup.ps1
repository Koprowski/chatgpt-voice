# Create Startup shortcuts: daemon in terminal + optional recording visualizer.
# Run from the chatgpt-voice folder: powershell -ExecutionPolicy Bypass -File install_startup.ps1
# Uses this folder's venv (e.g. run from C:\Tools\chatgpt-voice if that's your install).

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

# 1. Daemon in terminal (opens cmd, runs daemon so you see logs)
$WScript = New-Object -ComObject WScript.Shell
$Shortcut = $WScript.CreateShortcut((Join-Path $STARTUP "ChatGPT Voice (Terminal).lnk"))
$Shortcut.TargetPath = "cmd.exe"
$Shortcut.Arguments = "/k `"`"$PYTHON`" -m chatgpt_voice start`""
$Shortcut.WorkingDirectory = $DIR
$Shortcut.Description = "ChatGPT Voice daemon in terminal"
$Shortcut.Save()
Write-Host "Created: ChatGPT Voice (Terminal).lnk" -ForegroundColor Green

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
Write-Host "On login: a terminal will run the daemon; the visualizer runs in the background." -ForegroundColor Cyan
Write-Host "When you press Ctrl+Shift+. and record, a small wave window appears." -ForegroundColor Cyan
Write-Host "To remove: delete the shortcuts from $STARTUP" -ForegroundColor Gray
