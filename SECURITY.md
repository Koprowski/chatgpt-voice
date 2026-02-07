# Security

## For users

- **No API keys or credentials** are required. The app uses ChatGPT's web interface with your browser session (you log in once via `python -m chatgpt_voice login`).
- **Config and runtime data** (config.json, Chrome profile, PID files, logs) live in platform directories (`%APPDATA%\chatgpt-voice` on Windows, `~/.config/chatgpt-voice` on Linux, etc.) and are not part of this repository.
- **IPC** is local only: Unix socket (Linux/macOS) or TCP `127.0.0.1:52384` (Windows). No network exposure.
- **Transcription** is sent to ChatGPT's servers when you use voice input (same as using ChatGPT in a normal browser).

## For contributors

- Do not commit `.env`, `*.key`, `*.pem`, `config.json`, or other secrets. `.gitignore` is set up to exclude them.
- If you find a vulnerability, please report it responsibly (e.g. via GitHub Security Advisories or private contact if you prefer).
