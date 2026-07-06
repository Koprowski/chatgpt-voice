# Kill any running chatgpt-voice daemon + visualizer (and their Playwright
# node workers + orphaned Chromium), then relaunch from this folder's venv.
# Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File restart.ps1

$ErrorActionPreference = 'Stop'

$DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VENV = Join-Path $DIR 'venv'
$PYTHON = Join-Path $VENV 'Scripts\python.exe'
$PYTHONW = Join-Path $VENV 'Scripts\pythonw.exe'
$LOCAL_CONFIG_DIR = Join-Path $env:LOCALAPPDATA 'chatgpt-voice'
$VISUALIZER_PID = Join-Path $LOCAL_CONFIG_DIR 'visualizer.pid'

function Get-ChatGptVoiceProcess {
    param([string]$Role)

    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -like '*chatgpt_voice*' -and
            (!$Role -or $_.CommandLine -like "*chatgpt_voice*$Role*")
        }
}

function Stop-ChatGptVoiceProcess {
    param([string]$Role)

    Get-ChatGptVoiceProcess -Role $Role |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            } catch {
                Write-Warning "Failed to stop process $($_.ProcessId): $($_.Exception.Message)"
            }
        }
}

function Test-DaemonStatus {
    try {
        $status = & $PYTHON -m chatgpt_voice status 2>&1
        return ($LASTEXITCODE -eq 0 -and ($status -join "`n") -match '"status"\s*:')
    } catch {
        return $false
    }
}

function Wait-ForDaemon {
    param([int]$TimeoutSeconds = 20)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-DaemonStatus) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return $false
}

function Get-LiveVisualizer {
    Get-ChatGptVoiceProcess -Role 'visualizer'
}

function Wait-ForVisualizer {
    param([int]$TimeoutSeconds = 8)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $visualizers = @(Get-LiveVisualizer)
        if ($visualizers.Count -gt 0) {
            return $visualizers
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return @()
}

function Start-Visualizer {
    $visualizerPython = if (Test-Path $PYTHONW) { $PYTHONW } else { $PYTHON }
    $process = Start-Process -FilePath $visualizerPython `
        -ArgumentList '-m','chatgpt_voice','visualizer' `
        -WorkingDirectory $DIR `
        -WindowStyle Hidden `
        -PassThru

    New-Item -ItemType Directory -Force -Path $LOCAL_CONFIG_DIR | Out-Null
    Set-Content -LiteralPath $VISUALIZER_PID -Value $process.Id -Encoding ASCII
}

if (-not (Test-Path $PYTHON)) {
    Write-Host "Virtualenv not found at $VENV. Run setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

# 1. Try graceful shutdown via IPC so the daemon can close Chromium cleanly.
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect('127.0.0.1', 52384)
    $stream = $client.GetStream()
    $bytes = [Text.Encoding]::ASCII.GetBytes('quit')
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()
    Start-Sleep -Milliseconds 200
    $client.Close()

    for ($i = 0; $i -lt 20; $i++) {
        $alive = @(Get-ChatGptVoiceProcess -Role 'start')
        if ($alive.Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    }
} catch {
    # No daemon listening, or it did not accept quit. The force-kill pass below
    # handles stale processes.
}

# 2. Force-kill any stragglers, including old visualizer-only processes.
Stop-ChatGptVoiceProcess -Role $null

Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*chatgpt-voice*playwright*' -or $_.CommandLine -like '*playwright*chatgpt-voice*' } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { Write-Warning "Failed to stop node process $($_.ProcessId): $($_.Exception.Message)" }
    }

$profileDir = Join-Path $env:LOCALAPPDATA 'chatgpt-voice\chrome-profile'
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$profileDir*" -or $_.CommandLine -like '*ms-playwright*chatgpt*' } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { Write-Warning "Failed to stop chrome process $($_.ProcessId): $($_.Exception.Message)" }
    }

Remove-Item -LiteralPath $VISUALIZER_PID -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# 3. Relaunch daemon detached and verify it responds.
Start-Process -FilePath $PYTHON `
    -ArgumentList '-m','chatgpt_voice','start' `
    -WorkingDirectory $DIR `
    -WindowStyle Hidden | Out-Null

if (-not (Wait-ForDaemon -TimeoutSeconds 25)) {
    Write-Host "ChatGPT Voice daemon did not become healthy after restart." -ForegroundColor Red
    Write-Host "Run this in a console to see the startup error:" -ForegroundColor Yellow
    Write-Host "`"$PYTHON`" -m chatgpt_voice start"
    exit 1
}

# The daemon normally launches the visualizer. If it does not, start it here
# and verify a live overlay process exists.
$visualizers = @(Wait-ForVisualizer -TimeoutSeconds 5)
if ($visualizers.Count -eq 0) {
    Start-Visualizer
    $visualizers = @(Wait-ForVisualizer -TimeoutSeconds 8)
}

if ($visualizers.Count -eq 0) {
    Write-Host "ChatGPT Voice daemon restarted, but the waveform visualizer did not stay running." -ForegroundColor Red
    Write-Host "Run this in a console to see the visualizer error:" -ForegroundColor Yellow
    Write-Host "`"$PYTHON`" -m chatgpt_voice visualizer"
    exit 1
}

$visualizerIds = ($visualizers | Select-Object -ExpandProperty ProcessId) -join ', '
Write-Host "ChatGPT Voice daemon restarted from $DIR" -ForegroundColor Green
Write-Host "Waveform visualizer running (PID $visualizerIds)" -ForegroundColor Green
Write-Host "Status: $((& $PYTHON -m chatgpt_voice status 2>&1) -join ' ')" -ForegroundColor Cyan
