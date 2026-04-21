# Kill any running chatgpt-voice daemon + visualizer (and their playwright
# node workers), then relaunch both from this folder's venv.
# Run: powershell -ExecutionPolicy Bypass -File restart.ps1

$ErrorActionPreference = 'SilentlyContinue'

$DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VENV = Join-Path $DIR 'venv'
$PYTHON = Join-Path $VENV 'Scripts\python.exe'
$PYTHONW = Join-Path $VENV 'Scripts\pythonw.exe'

if (-not (Test-Path $PYTHON)) {
    Write-Host "Virtualenv not found at $VENV. Run setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

# Kill python/pythonw processes that are running chatgpt_voice
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*chatgpt_voice*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Kill any playwright node workers spawned by the daemon
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -like '*chatgpt-voice*playwright*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Start-Sleep -Milliseconds 500

Start-Process -FilePath $PYTHON  -ArgumentList '-m','chatgpt_voice','start'      -WorkingDirectory $DIR | Out-Null
Start-Process -FilePath $PYTHONW -ArgumentList '-m','chatgpt_voice','visualizer' -WorkingDirectory $DIR | Out-Null

Write-Host "ChatGPT Voice daemon + visualizer restarted from $DIR" -ForegroundColor Green
