# Kill any running chatgpt-voice daemon + visualizer (and their playwright
# node workers + orphaned Chromium), then relaunch both from this folder's venv.
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

# 1. Try graceful shutdown via IPC — lets the daemon close Chromium cleanly.
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect('127.0.0.1', 52384)
    $stream = $client.GetStream()
    $bytes = [Text.Encoding]::ASCII.GetBytes('quit')
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()
    Start-Sleep -Milliseconds 200
    $client.Close()
    # Give the daemon up to 4s to exit gracefully
    for ($i = 0; $i -lt 20; $i++) {
        $alive = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like '*chatgpt_voice*start*' }
        if (-not $alive) { break }
        Start-Sleep -Milliseconds 200
    }
} catch {
    # No daemon listening — fall through to force-kill
}

# 2. Force-kill any stragglers.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*chatgpt_voice*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -like '*chatgpt-voice*playwright*' -or $_.CommandLine -like '*playwright*chatgpt-voice*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Orphaned Playwright Chromium using our profile dir.
$profileDir = Join-Path $env:LOCALAPPDATA 'chatgpt-voice\chrome-profile'
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -like "*$profileDir*" -or $_.CommandLine -like '*ms-playwright*chatgpt*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Start-Sleep -Milliseconds 500

# 3. Relaunch daemon + visualizer detached.
Start-Process -FilePath $PYTHON  -ArgumentList '-m','chatgpt_voice','start'      -WorkingDirectory $DIR | Out-Null
Start-Process -FilePath $PYTHONW -ArgumentList '-m','chatgpt_voice','visualizer' -WorkingDirectory $DIR | Out-Null

Write-Host "ChatGPT Voice daemon + visualizer restarted from $DIR" -ForegroundColor Green
