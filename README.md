# chatgpt-voice

System-wide voice dictation using ChatGPT's free web transcription. Trigger with a global hotkey; transcribed text is pasted into the focused field.

- **Hotkey:** `Ctrl+Shift+.` (configurable)
- **Recording indicator:** Scrolling waveform window (ChatGPT-style) when recording
- **Platforms:** Windows, Linux, macOS

## Quick start (Windows)

```powershell
cd C:\path\to\chatgpt-voice
python -m venv venv
.\venv\Scripts\activate
pip install -e ".[windows]"
python -m chatgpt_voice login   # one-time: open browser, sign in to ChatGPT
python -m chatgpt_voice start   # daemon + visualizer
```

Then press **Ctrl+Shift+.** to toggle recording. See `IMPLEMENTATION_GUIDE.md` for Linux/macOS and details.

## Commands

| Command | Description |
|---------|-------------|
| `python -m chatgpt_voice start` | Start daemon and waveform visualizer |
| `python -m chatgpt_voice stop` | Stop daemon |
| `python -m chatgpt_voice login` | Re-authenticate with ChatGPT (browser) |
| `python -m chatgpt_voice status` | Show daemon status |
| `python -m chatgpt_voice toggle` | Toggle recording (same as hotkey) |
| `python -m chatgpt_voice visualizer` | Run only the waveform window (for testing) |

## Config

- **Windows:** `%APPDATA%\chatgpt-voice\config.json`
- **Linux:** `~/.config/chatgpt-voice/config.json`
- **macOS:** `~/Library/Application Support/chatgpt-voice/config.json`

Optional: `"hotkey": "ctrl+shift+."` (default).

## License

Same as parent project from which this was extracted.
