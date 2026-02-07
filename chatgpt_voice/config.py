"""Configuration loading and platform-aware paths."""

import json
import logging
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

log = logging.getLogger("chatgpt-voice")

DEFAULT_CONFIG = {
    "chatgpt_url": "https://chatgpt.com/",
    "hotkey": "ctrl+shift+.",
    "selectors": {
        "mic_button": [
            'button[aria-label="Dictate button" i]',
            'button[aria-label*="Dictate" i]:not([aria-label*="Stop" i]):not([aria-label*="Submit" i])',
        ],
        "stop_button": [
            'button[aria-label="Submit dictation" i]',
            'button[aria-label="Stop dictation" i]',
        ],
        "input_area": [
            "#prompt-textarea",
            '[id="prompt-textarea"]',
            'div[contenteditable="true"]',
        ],
    },
    "post_stop_poll_interval_ms": 200,
    "post_stop_poll_timeout_ms": 10000,
}

_APP_NAME = "chatgpt-voice"


def _config_dir() -> Path:
    return Path(user_config_dir(_APP_NAME, appauthor=False))


def _data_dir() -> Path:
    return Path(user_data_dir(_APP_NAME, appauthor=False))


def config_dir() -> Path:
    """Return the platform-appropriate config directory.

    Linux:   ~/.config/chatgpt-voice/
    Windows: %APPDATA%/chatgpt-voice/
    macOS:   ~/Library/Application Support/chatgpt-voice/
    """
    return _config_dir()


def data_dir() -> Path:
    """Return the platform-appropriate data directory (for chrome profile etc).

    Linux:   ~/.local/share/chatgpt-voice/
    Windows: %LOCALAPPDATA%/chatgpt-voice/
    macOS:   ~/Library/Application Support/chatgpt-voice/
    """
    return _data_dir()


def profile_dir() -> Path:
    """Return the chrome-profile directory, auto-migrating from legacy location."""
    new = data_dir() / "chrome-profile"
    if new.exists():
        # Clean up stale Singleton files left by a previous session so
        # Chromium doesn't refuse to launch with "Opening in existing
        # browser session".
        for stale in new.glob("Singleton*"):
            stale.unlink(missing_ok=True)
        return new

    # Legacy location (pre-refactor Linux)
    legacy = Path.home() / ".config" / "chatgpt-voice" / "chrome-profile"
    if legacy.exists():
        # Don't migrate while Chrome is actively using the old path
        if (legacy / "SingletonLock").exists():
            log.info("Legacy chrome-profile is locked by a running browser, using it in place")
            return legacy
        log.info("Migrating chrome-profile from %s to %s", legacy, new)
        new.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(new)
        # Clean up Singleton files from the moved profile
        for stale in new.glob("Singleton*"):
            stale.unlink(missing_ok=True)
        return new

    return new


def config_file() -> Path:
    return config_dir() / "config.json"


def log_file() -> Path:
    return config_dir() / "daemon.log"


def load_config() -> dict:
    """Load and merge user config with defaults."""
    cdir = config_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    cf = config_file()

    if cf.exists():
        with open(cf) as f:
            user = json.load(f)
        merged = {**DEFAULT_CONFIG, **user}
        merged["selectors"] = {
            **DEFAULT_CONFIG["selectors"],
            **user.get("selectors", {}),
        }
        return merged
    else:
        with open(cf, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG
