"""Platform abstraction layer.

Detects the OS (and display server on Linux) and dispatches to the
appropriate backend for clipboard, paste simulation, notifications,
and global hotkey registration.
"""

import logging
import os
import shlex
import subprocess
import sys
import threading
import time

log = logging.getLogger("chatgpt-voice")

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

PLATFORM: str  # "linux-wayland", "linux-x11", "windows", "darwin"

if sys.platform == "win32":
    PLATFORM = "windows"
elif sys.platform == "darwin":
    PLATFORM = "darwin"
else:
    # Linux — detect display server
    _session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    _wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    if _session_type == "wayland" or _wayland_display:
        PLATFORM = "linux-wayland"
    else:
        PLATFORM = "linux-x11"


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def copy_to_clipboard(text: str) -> None:
    """Copy *text* to the system clipboard."""
    if PLATFORM == "linux-wayland":
        subprocess.run(["wl-copy", "--", text], check=True, timeout=5)
    elif PLATFORM == "linux-x11":
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(),
            check=True,
            timeout=5,
        )
    elif PLATFORM == "windows":
        import pyperclip
        pyperclip.copy(text)
    elif PLATFORM == "darwin":
        subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=5)
    else:
        raise RuntimeError(f"Unsupported platform: {PLATFORM}")


# ---------------------------------------------------------------------------
# Paste simulation
# ---------------------------------------------------------------------------

def simulate_paste() -> None:
    """Inject a paste keystroke into the currently focused window."""
    if PLATFORM == "linux-wayland":
        _paste_evdev()
    elif PLATFORM == "linux-x11":
        _paste_pynput(ctrl_shift_v=True)
    elif PLATFORM == "windows":
        _paste_pynput(ctrl_shift_v=False)
    elif PLATFORM == "darwin":
        _paste_pynput_mac()
    else:
        raise RuntimeError(f"Unsupported platform: {PLATFORM}")


def _paste_evdev() -> None:
    """Simulate Ctrl+Shift+V via Linux uinput (works on Wayland)."""
    import evdev
    from evdev import UInput, ecodes

    with UInput() as ui:
        ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
        ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
        ui.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
        ui.syn()
        time.sleep(0.05)
        ui.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
        ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
        ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
        ui.syn()


def _paste_pynput(ctrl_shift_v: bool = False) -> None:
    """Simulate paste via pynput (X11 / Windows)."""
    from pynput.keyboard import Controller, Key

    kb = Controller()
    if ctrl_shift_v:
        with kb.pressed(Key.ctrl, Key.shift):
            kb.press("v")
            kb.release("v")
    else:
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")


def _paste_pynput_mac() -> None:
    """Simulate Cmd+V via pynput (macOS)."""
    from pynput.keyboard import Controller, Key

    kb = Controller()
    with kb.pressed(Key.cmd):
        kb.press("v")
        kb.release("v")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def send_notification(title: str, body: str = "", timeout: float = 3) -> None:
    """Show a desktop notification that auto-closes after timeout seconds.

    On GNOME, notify-send timeout hints are ignored, so we use gdbus to
    send via D-Bus and then close the notification ourselves.
    """
    try:
        if PLATFORM.startswith("linux"):
            ms = int(timeout * 1000)

            def _send():
                try:
                    result = subprocess.run(
                        ["gdbus", "call", "--session",
                         "--dest", "org.freedesktop.Notifications",
                         "--object-path", "/org/freedesktop/Notifications",
                         "--method", "org.freedesktop.Notifications.Notify",
                         "ChatGPT Voice", "0", "", title, body,
                         "[]", "{}", str(ms)],
                        capture_output=True, text=True, timeout=5,
                    )
                    out = result.stdout.strip()
                    if out.startswith("(uint32 "):
                        nid = out.split()[1].rstrip(",)")
                        time.sleep(timeout)
                        subprocess.run(
                            ["gdbus", "call", "--session",
                             "--dest", "org.freedesktop.Notifications",
                             "--object-path", "/org/freedesktop/Notifications",
                             "--method", "org.freedesktop.Notifications.CloseNotification",
                             nid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                        )
                except Exception:
                    pass

            threading.Thread(target=_send, daemon=True).start()
        elif PLATFORM == "windows":
            _notify_windows(title, body, timeout)
        elif PLATFORM == "darwin":
            _notify_macos(title, body)
    except Exception:
        log.debug("Notification failed", exc_info=True)


def _notify_windows(title: str, body: str, timeout: float = 3) -> None:
    """Windows: win10toast respects duration (for short toasts); plyer timeout is ignored."""
    # For short duration (e.g. 1s startup toast), use win10toast so it actually disappears
    if timeout <= 5:
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(
                title,
                body or " ",
                duration=max(1, int(timeout)),
                threaded=True,
            )
            return
        except Exception:
            pass
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=body or " ",
            app_name="ChatGPT Voice",
            timeout=timeout,
        )
    except Exception:
        env = {**os.environ, "_NOTIFY_TITLE": title, "_NOTIFY_BODY": body or " "}
        subprocess.Popen(
            [
                "powershell", "-NoProfile", "-Command",
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(0); "
                "$text = $template.GetElementsByTagName('text'); "
                "$text[0].AppendChild($template.CreateTextNode($env:_NOTIFY_TITLE + ': ' + $env:_NOTIFY_BODY)) | Out-Null; "
                "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ChatGPT Voice'); "
                "$notifier.Show([Windows.UI.Notifications.ToastNotification]::new($template))",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )


def _notify_macos(title: str, body: str) -> None:
    """macOS notification via osascript."""
    script = f'display notification {_applescript_string(body or "")} with title {_applescript_string(title)}'
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _applescript_string(s: str) -> str:
    """Safely quote a string for AppleScript by escaping backslashes and double quotes."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Global hotkey registration
# ---------------------------------------------------------------------------

def register_global_hotkey(hotkey: str, callback) -> object | None:
    """Register a global hotkey that calls *callback* when pressed.

    Returns an opaque listener object (call .stop() to unregister), or
    None on platforms where global hotkeys must be handled externally
    (e.g. Linux Wayland → GNOME gsettings).

    *hotkey* is a human-readable string like "ctrl+shift+." — interpretation
    is platform-specific.
    """
    if PLATFORM == "linux-wayland":
        # Wayland blocks userspace global hotkey capture.
        # Use GNOME custom keyboard shortcuts → toggle script instead.
        return None

    if PLATFORM in ("linux-x11", "windows", "darwin"):
        return _register_pynput_hotkey(hotkey, callback)

    return None


def _register_pynput_hotkey(hotkey: str, callback) -> object:
    """Register via pynput GlobalHotKeys."""
    from pynput import keyboard

    # Translate human-readable combo to pynput format
    pynput_combo = _to_pynput_hotkey(hotkey)
    listener = keyboard.GlobalHotKeys({pynput_combo: callback})
    listener.daemon = True
    listener.start()
    return listener


def _to_pynput_hotkey(hotkey: str) -> str:
    """Convert 'ctrl+shift+.' to pynput '<ctrl>+<shift>+.' format."""
    parts = [p.strip().lower() for p in hotkey.split("+")]
    translated = []
    for p in parts:
        if p in ("ctrl", "control"):
            translated.append("<ctrl>")
        elif p in ("shift",):
            translated.append("<shift>")
        elif p in ("alt",):
            translated.append("<alt>")
        elif p in ("cmd", "command", "super", "win"):
            translated.append("<cmd>")
        else:
            translated.append(p)
    return "+".join(translated)
