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
