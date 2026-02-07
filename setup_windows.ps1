# ChatGPT Voice Transcription — Windows Setup
# Run: powershell -ExecutionPolicy Bypass -File setup_windows.ps1

$ErrorActionPreference = "Stop"
$DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VENV = Join-Path $DIR "venv"

Write-Host "=== ChatGPT Voice Transcription Setup (Windows) ===" -ForegroundColor Cyan
Write-Host ""

# 1. Create virtualenv
Write-Host "[1/5] Setting up Python virtualenv..."
if (-not (Test-Path $VENV)) {
    python -m venv $VENV
}
& "$VENV\Scripts\pip.exe" install --quiet --upgrade pip

# 2. Install dependencies
Write-Host "[2/5] Installing dependencies..."
& "$VENV\Scripts\pip.exe" install --quiet ".[windows]"

# 3. Install Playwright Chromium
Write-Host "[3/5] Installing Playwright Chromium..."
& "$VENV\Scripts\python.exe" -m playwright install chromium

# 4. Create config directory
Write-Host "[4/5] Creating config directory..."
$CONFIG_DIR = Join-Path $env:APPDATA "chatgpt-voice"
if (-not (Test-Path $CONFIG_DIR)) {
    New-Item -ItemType Directory -Path $CONFIG_DIR -Force | Out-Null
}

# 5. Create startup shortcut (optional)
Write-Host "[5/5] Creating startup shortcut..."
$STARTUP = [Environment]::GetFolderPath("Startup")
$SHORTCUT_PATH = Join-Path $STARTUP "ChatGPT Voice.lnk"

if (-not (Test-Path $SHORTCUT_PATH)) {
    $WScript = New-Object -ComObject WScript.Shell
    $Shortcut = $WScript.CreateShortcut($SHORTCUT_PATH)
    $Shortcut.TargetPath = "$VENV\Scripts\pythonw.exe"
    $Shortcut.Arguments = "-m chatgpt_voice start"
    $Shortcut.WorkingDirectory = $DIR
    $Shortcut.Description = "ChatGPT Voice Transcription Daemon"
    $Shortcut.Save()
    Write-Host "  Startup shortcut created at: $SHORTCUT_PATH"
} else {
    Write-Host "  Startup shortcut already exists."
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Log in to ChatGPT (one-time; requires paid account, e.g. Plus):"
Write-Host "     $VENV\Scripts\python.exe -m chatgpt_voice login"
Write-Host "     (Sign in with your paid ChatGPT account in the browser that opens, then Ctrl+C)"
Write-Host ""
Write-Host "  2. Start the daemon:"
Write-Host "     $VENV\Scripts\python.exe -m chatgpt_voice start"
Write-Host ""
Write-Host "  3. Press Ctrl+Shift+. to toggle voice recording"
Write-Host "     (Global hotkey is registered automatically by the daemon)"
Write-Host ""
Write-Host "  To stop the daemon:"
Write-Host "     $VENV\Scripts\python.exe -m chatgpt_voice stop"
Write-Host ""
