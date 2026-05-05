$ErrorActionPreference = "Stop"

$DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PYTHONW = Join-Path $DIR "venv\Scripts\pythonw.exe"

if (-not (Test-Path $PYTHONW)) {
    Write-Host "venv not found at $DIR\venv. Run setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$TaskName = "ChatGPT Voice Daemon"

$Action = New-ScheduledTaskAction -Execute $PYTHONW -Argument "-m chatgpt_voice start" -WorkingDirectory $DIR

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Trigger.Delay = "PT10S"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName" -ForegroundColor Yellow
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "ChatGPT Voice daemon. Starts 15s after login, only if network is available, retries on failure." | Out-Null

Write-Host "Registered scheduled task: $TaskName" -ForegroundColor Green

# Remove the legacy Startup folder shortcut so we don't double-launch.
$STARTUP = [Environment]::GetFolderPath("Startup")
$OldShortcut = Join-Path $STARTUP "ChatGPT Voice.lnk"
if (Test-Path $OldShortcut) {
    Remove-Item $OldShortcut
    Write-Host "Removed Startup folder shortcut: ChatGPT Voice.lnk" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "To run now:    Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Cyan
Write-Host "To inspect:    Get-ScheduledTaskInfo -TaskName '$TaskName'" -ForegroundColor Cyan
Write-Host "To remove:     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Cyan
