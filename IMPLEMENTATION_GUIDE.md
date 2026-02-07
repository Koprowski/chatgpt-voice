# ChatGPT Voice Transcription Daemon — Implementation Guide

## Overview

A background daemon that piggybacks ChatGPT's free web-based voice transcription (server-side Whisper) to provide system-wide dictation. Press a keyboard shortcut to start recording, press again to stop — transcribed text is copied to clipboard and auto-pasted into the currently focused text field.

**Supported platforms:** Linux (Wayland/X11), Windows, macOS.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Hotkey trigger                                              │
│  ├─ Linux Wayland: GNOME custom shortcut → toggle script     │
│  ├─ Linux X11 / Windows / macOS: pynput global hotkey        │
│  └─ CLI: python -m chatgpt_voice toggle                      │
└──────────────┬───────────────────────────────────────────────┘
               │ IPC (Unix socket or TCP localhost)
               ▼
┌──────────────────────────────────────────────────────────────┐
│  VoiceDaemon (Python asyncio)                                │
│  ├─ Playwright persistent Chromium (minimized)               │
│  │  └─ ChatGPT tab with visibility API override              │
│  ├─ IPC server (Unix socket / TCP 127.0.0.1:52384)          │
│  ├─ Clipboard (wl-copy / xclip / pyperclip / pbcopy)        │
│  └─ Paste injection (evdev / pynput)                         │
└──────────────────────────────────────────────────────────────┘
```

**Flow:**
1. User presses hotkey from any application
2. Hotkey fires toggle → sends `toggle` to daemon via IPC
3. Daemon uses Playwright to click ChatGPT's microphone button in a minimized Chromium instance
4. User speaks
5. User presses hotkey again
6. Daemon clicks stop, polls for transcribed text in the input area
7. Text is copied to clipboard via platform-appropriate tool
8. Paste keystroke is injected at the OS level
9. Text appears in whatever field was focused

## File Structure

```
~/chatgpt-voice/
├── pyproject.toml                  # Package metadata, deps, entry points
├── setup.sh                        # Linux setup
├── setup_windows.ps1               # Windows setup
├── toggle                          # Linux GNOME backward-compat wrapper
├── chatgpt_voice/
│   ├── __init__.py
│   ├── __main__.py                 # CLI: python -m chatgpt_voice {start|login|stop|toggle|status}
│   ├── daemon.py                   # Core VoiceDaemon (platform-agnostic)
│   ├── config.py                   # Config loading, paths via platformdirs
│   ├── platform_utils.py           # Clipboard, paste, notifications, hotkeys
│   └── ipc.py                      # Unix socket (Linux/macOS) or TCP localhost (Windows)
├── IMPLEMENTATION_GUIDE.md
└── WHY_THIS_APPROACH.md
```

### Platform-specific behavior

| Function | Linux Wayland | Linux X11 | Windows | macOS |
|----------|--------------|-----------|---------|-------|
| Clipboard | `wl-copy` | `xclip` | `pyperclip` | `pbcopy` |
| Paste | `evdev` uinput Ctrl+Shift+V | `pynput` Ctrl+Shift+V | `pynput` Ctrl+V | `pynput` Cmd+V |
| Notifications | `notify-send` | `notify-send` | `plyer` / PowerShell toast | `osascript` |
| Global hotkey | None (GNOME gsettings) | `pynput` | `pynput` | `pynput` |
| IPC | Unix socket | Unix socket | TCP `127.0.0.1:52384` | Unix socket |
| Config dir | `~/.config/chatgpt-voice/` | same | `%APPDATA%/chatgpt-voice/` | `~/Library/Application Support/chatgpt-voice/` |
| Data dir | `~/.local/share/chatgpt-voice/` | same | `%LOCALAPPDATA%/chatgpt-voice/` | `~/Library/Application Support/chatgpt-voice/` |

## Environment

### Linux
- **OS:** Ubuntu 24.04 (or similar Debian-based) / any distro with GNOME
- **Display server:** Wayland or X11
- **Desktop:** GNOME (for keyboard shortcut registration)
- **Python:** 3.11+

### Windows
- **OS:** Windows 10/11
- **Python:** 3.11+

### macOS
- **OS:** macOS 12+
- **Python:** 3.11+

## Prerequisites

### Linux

System packages:
```bash
sudo apt install -y wl-clipboard python3-venv libnotify-bin
# For X11: sudo apt install -y xclip
```

User must be in the `input` group (for uinput access on Wayland):
```bash
sudo usermod -aG input $USER
# Log out and back in for group change to take effect
```

uinput device permissions (persistent across reboots):
```bash
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/80-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Windows

No special prerequisites beyond Python 3.11+. All dependencies are installed via `setup_windows.ps1`.

### macOS

No special prerequisites beyond Python 3.11+. Accessibility permissions may be needed for pynput (System Settings → Privacy & Security → Accessibility).

## Setup

### Linux
```bash
cd ~/chatgpt-voice
./setup.sh
```

### Windows
```powershell
cd ~/chatgpt-voice
powershell -ExecutionPolicy Bypass -File setup_windows.ps1
```

### All platforms — first login
```bash
python -m chatgpt_voice login
# Log in to ChatGPT in the browser, then Ctrl+C
```

## Usage

```bash
# Start daemon
python -m chatgpt_voice start

# Stop daemon
python -m chatgpt_voice stop

# Check status
python -m chatgpt_voice status

# Manual toggle
python -m chatgpt_voice toggle
```

### Linux systemd service (auto-start on login)

```ini
# ~/.config/systemd/user/chatgpt-voice.service
[Unit]
Description=ChatGPT Voice Transcription Daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/chatgpt-voice/venv/bin/python3 -m chatgpt_voice start
ExecStop=%h/chatgpt-voice/venv/bin/python3 -m chatgpt_voice stop
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable chatgpt-voice.service
systemctl --user start chatgpt-voice.service
```

## Configuration

`config.json` is created on first run in the platform-appropriate config directory. Update selectors here when ChatGPT changes their UI:

```json
{
  "chatgpt_url": "https://chatgpt.com/",
  "hotkey": "ctrl+shift+.",
  "selectors": {
    "mic_button": [
      "[data-testid=\"composer-speech-button\"]",
      "button[aria-label*=\"Start voice\" i]"
    ],
    "stop_button": [
      "[data-testid=\"composer-speech-stop-button\"]",
      "button[aria-label*=\"Stop\" i]"
    ],
    "input_area": [
      "#prompt-textarea",
      "[id=\"prompt-textarea\"]",
      "div[contenteditable=\"true\"]"
    ]
  },
  "post_stop_poll_interval_ms": 200,
  "post_stop_poll_timeout_ms": 10000
}
```

The `hotkey` field is used by pynput on non-Wayland platforms. On Linux Wayland, the hotkey is configured via GNOME keyboard shortcuts (set by `setup.sh`).

## Troubleshooting

**Shortcut not firing (Linux):**
- Check for conflicts: `gsettings list-recursively | grep "<Ctrl><Shift>period"`
- Verify registration: `gsettings get "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/chatgpt-voice/" binding`

**Daemon not responding:**
- Check status: `python -m chatgpt_voice status`
- Linux: `systemctl --user status chatgpt-voice`
- Check socket/port: `ls -la /tmp/chatgpt-voice.sock` (Linux) or `netstat -an | findstr 52384` (Windows)

**Paste not working (Linux Wayland):**
- Verify uinput permissions: `ls -la /dev/uinput` (should be `crw-rw---- root input`)
- Verify user in input group: `groups $USER | grep input`
- Test clipboard: `wl-paste` after a transcription

**Paste not working (Windows/macOS):**
- Ensure no other app is intercepting the hotkey
- Try running with admin/elevated privileges once

**ChatGPT session expired:**
- Stop daemon, run `python -m chatgpt_voice login`, re-authenticate, Ctrl+C, restart daemon

## Technologies Used

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Browser automation | Playwright (Python) | Control minimized Chromium with ChatGPT |
| Browser engine | Chromium (Playwright-managed) | Hosts ChatGPT with persistent login |
| Speech-to-text | ChatGPT's server-side Whisper | Free, fast, accurate transcription |
| IPC | asyncio Unix socket / TCP | Communication between trigger and daemon |
| Clipboard | wl-copy / xclip / pyperclip / pbcopy | Set system clipboard contents |
| Keystroke injection | evdev uinput / pynput | Simulate paste keystroke |
| Global hotkey | GNOME shortcuts / pynput | Trigger from any application |
| Auto-start | systemd / Windows Startup / (macOS launchd) | Start daemon on login |
| Notifications | notify-send / plyer / osascript | Visual feedback for recording state |
| Window management | CDP Browser.setWindowBounds | Minimize Playwright browser |
| Visibility override | JavaScript injection | Keep mic active while minimized |
| Config paths | platformdirs | Cross-platform config/data directories |
