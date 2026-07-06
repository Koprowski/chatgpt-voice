"""Configuration loading and platform-aware paths."""

import copy
import json
import logging
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

log = logging.getLogger("chatgpt-voice")

DEFAULT_PROVIDERS = {
    "chatgpt": {
        "name": "ChatGPT",
        "url": "https://chatgpt.com/",
        "selectors": {
            "mic_button": [
                'button[aria-label="Start dictation" i]',
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
                "textarea",
            ],
            "login_indicator": [
                '[data-testid="login-button"]',
                'button[data-action="click:login"]',
            ],
        },
        "keywords": {
            "mic_button": ["start dictation", "dictate button", "dictate"],
            "stop_button": ["submit dictation", "stop dictation"],
            "recording": ["stop dictation", "submit dictation", "stop recording"],
            "processing": [
                "transcribing",
                "processing",
                "please wait",
                "cancel dictation",
                "finishing dictation",
            ],
            "login": ["log in", "sign in"],
        },
    },
    "gemini": {
        "name": "Gemini",
        "url": "https://gemini.google.com/",
        "selectors": {
            "mic_button": [
                'button[aria-label*="Microphone" i]',
                'button[aria-label*="Use microphone" i]',
                'button[aria-label*="Start voice" i]',
                'button[aria-label*="Voice input" i]',
                'button[aria-label*="Start speaking" i]',
                'button[aria-label*="Talk" i]',
            ],
            "stop_button": [
                'button[aria-label*="Stop recording" i]',
                'button[aria-label*="Stop speaking" i]',
                'button[aria-label*="Stop" i]',
                'button[aria-label*="Done" i]',
            ],
            "input_area": [
                'rich-textarea div[contenteditable="true"]',
                'div[contenteditable="true"][aria-label*="prompt" i]',
                'div[contenteditable="true"][aria-label*="message" i]',
                'div[contenteditable="true"]',
                "textarea",
            ],
            "login_indicator": [
                'a[href*="accounts.google.com"]',
                'button[aria-label*="Sign in" i]',
            ],
        },
        "keywords": {
            "mic_button": [
                "microphone",
                "use microphone",
                "start voice",
                "voice input",
                "start speaking",
                "talk",
            ],
            "stop_button": ["stop recording", "stop speaking", "stop", "done"],
            "recording": ["stop recording", "stop speaking", "listening", "recording"],
            "processing": ["transcribing", "processing", "converting speech"],
            "login": ["sign in", "use gemini", "continue to gemini"],
        },
    },
}

DEFAULT_CONFIG = {
    "provider": "chatgpt",
    "providers": DEFAULT_PROVIDERS,
    "diagnostics": {
        "enabled": False,
    },
    # Legacy aliases retained for existing local config files and old docs.
    "chatgpt_url": DEFAULT_PROVIDERS["chatgpt"]["url"],
    "selectors": DEFAULT_PROVIDERS["chatgpt"]["selectors"],
    "hotkey": "ctrl+shift+.",
    "post_stop_poll_interval_ms": 200,
    "post_stop_poll_timeout_ms": 60000,
    "post_stop_idle_no_text_timeout_ms": 15000,
    "post_stop_min_wait_ms": 1200,
    "post_stop_text_stable_ms": 1600,
    "post_stop_busy_grace_ms": 3000,
    "late_transcript_poll_interval_ms": 1000,
    "late_transcript_poll_timeout_ms": 300000,
}

_APP_NAME = "chatgpt-voice"


def _config_dir() -> Path:
    return Path(user_config_dir(_APP_NAME, appauthor=False))


def _data_dir() -> Path:
    return Path(user_data_dir(_APP_NAME, appauthor=False))


def config_dir() -> Path:
    """Return the platform-appropriate config directory.

    Linux:   ~/.config/chatgpt-voice/
    Windows: %LOCALAPPDATA%/chatgpt-voice/
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


def _merge_string_lists(defaults: list[str], user_value) -> list[str]:
    """Merge user string list with defaults while preserving order.

    User values are prioritized, but defaults are appended so UI updates keep
    existing installs working when local config files contain older values.
    """
    if not isinstance(user_value, list):
        return list(defaults)

    merged: list[str] = []
    seen: set[str] = set()
    for value in user_value + defaults:
        if not isinstance(value, str):
            continue
        selector = value.strip()
        if not selector or selector in seen:
            continue
        merged.append(selector)
        seen.add(selector)
    return merged


def _merge_selector_lists(defaults: list[str], user_value) -> list[str]:
    """Merge user selector list with defaults while preserving order."""
    return _merge_string_lists(defaults, user_value)


def _merge_selectors(defaults: dict, user_value) -> dict:
    """Deep-merge selector groups so defaults remain as fallbacks."""
    if not isinstance(user_value, dict):
        return copy.deepcopy(defaults)

    merged = {}
    for key, default_list in defaults.items():
        merged[key] = _merge_selector_lists(default_list, user_value.get(key))

    # Keep any user-defined custom selector groups intact.
    for key, value in user_value.items():
        if key not in merged:
            merged[key] = value

    return merged


def _merge_keywords(defaults: dict, user_value) -> dict:
    """Deep-merge keyword groups so provider heuristics stay current."""
    if not isinstance(user_value, dict):
        return copy.deepcopy(defaults)

    merged = {}
    for key, default_list in defaults.items():
        merged[key] = _merge_string_lists(default_list, user_value.get(key))
    for key, value in user_value.items():
        if key not in merged:
            merged[key] = value
    return merged


def _merge_provider(default_provider: dict, user_provider) -> dict:
    """Merge one provider config while retaining default selectors/keywords."""
    if not isinstance(user_provider, dict):
        return copy.deepcopy(default_provider)

    merged = {**copy.deepcopy(default_provider), **user_provider}
    if isinstance(default_provider.get("post_stop"), dict) or isinstance(user_provider.get("post_stop"), dict):
        merged["post_stop"] = {
            **copy.deepcopy(default_provider.get("post_stop", {})),
            **copy.deepcopy(user_provider.get("post_stop", {})),
        }
    merged["selectors"] = _merge_selectors(
        default_provider.get("selectors", {}),
        user_provider.get("selectors", {}),
    )
    merged["keywords"] = _merge_keywords(
        default_provider.get("keywords", {}),
        user_provider.get("keywords", {}),
    )
    return merged


def _merge_providers(defaults: dict, user_value) -> dict:
    """Merge provider map and keep unknown custom providers intact."""
    user_providers = user_value if isinstance(user_value, dict) else {}
    merged = {
        key: _merge_provider(default_provider, user_providers.get(key))
        for key, default_provider in defaults.items()
    }
    for key, value in user_providers.items():
        if key not in merged and isinstance(value, dict):
            merged[key] = copy.deepcopy(value)
    return merged


def _normalize_provider_id(config: dict) -> str:
    provider_id = str(config.get("provider") or "chatgpt").strip().lower()
    providers = config.get("providers", {})
    if provider_id not in providers:
        log.warning("Unknown provider '%s'; falling back to chatgpt", provider_id)
        return "chatgpt"
    return provider_id


def merge_config(user: dict | None) -> dict:
    """Return a fully merged config without reading or writing files."""
    user = user if isinstance(user, dict) else {}
    merged = {**copy.deepcopy(DEFAULT_CONFIG), **user}
    merged["providers"] = _merge_providers(
        DEFAULT_CONFIG["providers"],
        user.get("providers", {}),
    )

    # Fold legacy top-level ChatGPT settings into the ChatGPT provider.
    chatgpt_provider = merged["providers"]["chatgpt"]
    if isinstance(user.get("chatgpt_url"), str):
        chatgpt_provider["url"] = user["chatgpt_url"]
    if "selectors" in user:
        chatgpt_provider["selectors"] = _merge_selectors(
            DEFAULT_PROVIDERS["chatgpt"]["selectors"],
            user.get("selectors", {}),
        )

    merged["provider"] = _normalize_provider_id(merged)
    merged["chatgpt_url"] = chatgpt_provider["url"]
    merged["selectors"] = chatgpt_provider["selectors"]
    if not isinstance(merged.get("diagnostics"), dict):
        merged["diagnostics"] = copy.deepcopy(DEFAULT_CONFIG["diagnostics"])
    else:
        merged["diagnostics"] = {
            **copy.deepcopy(DEFAULT_CONFIG["diagnostics"]),
            **merged["diagnostics"],
        }
    return merged


def get_provider_config(config: dict, provider_id: str | None = None) -> dict:
    """Return the active provider config from a merged or partial config."""
    merged = merge_config(config)
    selected = (provider_id or merged["provider"]).strip().lower()
    if selected not in merged["providers"]:
        selected = "chatgpt"
    provider = copy.deepcopy(merged["providers"][selected])
    provider["id"] = selected
    return provider


def load_config() -> dict:
    """Load and merge user config with defaults."""
    cdir = config_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    cf = config_file()

    if cf.exists():
        with open(cf) as f:
            user = json.load(f)
        return merge_config(user)
    else:
        default_config = merge_config({})
        with open(cf, "w") as f:
            json.dump(default_config, f, indent=2)
        return default_config


def save_config(config: dict) -> dict:
    """Merge and write config.json, returning the normalized config."""
    merged = merge_config(config)
    cdir = config_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    with open(config_file(), "w") as f:
        json.dump(merged, f, indent=2)
    return merged
