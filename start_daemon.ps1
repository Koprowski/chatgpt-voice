$LOG = "C:\Users\kopro\AppData\Roaming\chatgpt-voice\daemon.log"
$null = New-Item -Force -ItemType Directory (Split-Path $LOG)
Start-Process `
    -FilePath "C:\Tools\chatgpt-voice-venv\Scripts\python.exe" `
    -ArgumentList "-m", "chatgpt_voice", "start" `
    -WindowStyle Hidden `
    -RedirectStandardError $LOG
