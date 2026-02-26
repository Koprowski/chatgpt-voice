$LOG = "C:\Users\kopro\AppData\Roaming\chatgpt-voice\daemon.log"
$null = New-Item -Force -ItemType Directory (Split-Path $LOG)
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting chatgpt-voice daemon" | Add-Content $LOG
& "C:\Tools\chatgpt-voice\venv\Scripts\python.exe" -m chatgpt_voice start *>> $LOG
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Daemon exited (code $LASTEXITCODE)" | Add-Content $LOG
