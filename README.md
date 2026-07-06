# chatgpt-voice

System-wide voice dictation using supported web voice transcription providers. Trigger with a global hotkey; transcribed text is pasted into the focused field.

- **ChatGPT provider:** requires an account with ChatGPT web voice dictation access.
- **Hotkey:** `Ctrl+Shift+.` (configurable)
- **Recording indicator:** Scrolling waveform window (ChatGPT-style) when recording
- **Provider selection:** Settings UI can switch between ChatGPT and Gemini web dictation
- **Diagnostics:** Settings UI can enable debug logs and test the active provider connection
- **Platforms:** Windows, Linux, macOS

**Important:** This app automates provider web interfaces and may conflict with provider terms of use. See [LEGAL.md](LEGAL.md) for details.

## Quick start (Windows)

```powershell
cd C:\path\to\chatgpt-voice
python -m venv venv
.\venv\Scripts\activate
pip install -e ".[windows]"
python -m chatgpt_voice login   # one-time: open browser, sign in with the selected provider account
python -m chatgpt_voice start   # daemon + visualizer
```

Then press **Ctrl+Shift+.** to toggle recording. On Windows, setup also creates a **ChatGPT Voice** desktop shortcut that opens the settings/control panel.

Closing the Windows settings window hides it to the notification area near the clock. Use the tray icon to reopen Settings or exit the Settings UI; the daemon keeps listening in the background unless you stop the service.

## Commands

| Command | Description |
|---------|-------------|
| `python -m chatgpt_voice start` | Start daemon and waveform visualizer |
| `python -m chatgpt_voice stop` | Stop daemon |
| `python -m chatgpt_voice login` | Re-authenticate with the selected provider (browser) |
| `python -m chatgpt_voice status` | Show daemon status |
| `python -m chatgpt_voice toggle` | Toggle recording (same as hotkey) |
| `python -m chatgpt_voice visualizer` | Run only the waveform window (for testing) |
| `python -m chatgpt_voice settings` | Open provider/settings control panel |
| `python -m chatgpt_voice test-connection` | Test the active provider via the running daemon |
| `python -m chatgpt_voice install-shortcuts` | Install Windows Desktop and Start Menu shortcuts |

## Config

- **Windows:** `%LOCALAPPDATA%\chatgpt-voice\config.json`
- **Linux:** `~/.config/chatgpt-voice/config.json`
- **macOS:** `~/Library/Application Support/chatgpt-voice/config.json`

Optional: `"hotkey": "ctrl+shift+."` (default).

Provider is controlled by `"provider": "chatgpt"` or `"provider": "gemini"`.
Gemini uses `https://gemini.google.com/` and requires you to be signed into a Google account in the Playwright browser profile.

## License

Same as parent project from which this was extracted.
