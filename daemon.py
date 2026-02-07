#!/usr/bin/env python3
"""ChatGPT Voice Transcription Daemon

Runs a minimized Playwright Chromium with ChatGPT open.
Listens on a Unix socket for toggle commands.
Records voice via ChatGPT's built-in transcription.
Copies result to clipboard via wl-copy.

Usage:
  daemon.py start       Start the daemon (browser minimized)
  daemon.py login       Open browser visibly for initial ChatGPT login
  daemon.py stop        Stop a running daemon
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

SOCKET_PATH = "/tmp/chatgpt-voice.sock"
PID_FILE = "/tmp/chatgpt-voice.pid"
CONFIG_DIR = Path.home() / ".config" / "chatgpt-voice"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "daemon.log"

# Check both profile locations; prefer whichever has actual data
_NEW_PROFILE = Path.home() / ".local" / "share" / "chatgpt-voice" / "chrome-profile"
_OLD_PROFILE = CONFIG_DIR / "chrome-profile"
if _NEW_PROFILE.exists() and any(_NEW_PROFILE.iterdir()):
    PROFILE_DIR = _NEW_PROFILE
else:
    PROFILE_DIR = _OLD_PROFILE

DEFAULT_CONFIG = {
    "chatgpt_url": "https://chatgpt.com/",
    "selectors": {
        "mic_button": [
            '[data-testid="composer-speech-button"]',
            'button[aria-label*="Start voice" i]',
            'button[aria-label*="Voice" i]',
            'button[aria-label*="microphone" i]',
        ],
        "stop_button": [
            '[data-testid="composer-speech-stop-button"]',
            'button[aria-label*="Stop" i]',
            'button[aria-label*="Done" i]',
        ],
        "input_area": [
            '#prompt-textarea',
            '[id="prompt-textarea"]',
            'div[contenteditable="true"]',
        ],
    },
    "post_stop_poll_interval_ms": 200,
    "post_stop_poll_timeout_ms": 10000,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("chatgpt-voice")


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            user = json.load(f)
        # Merge with defaults
        merged = {**DEFAULT_CONFIG, **user}
        merged["selectors"] = {**DEFAULT_CONFIG["selectors"], **user.get("selectors", {})}
        return merged
    else:
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG


def notify(title, body=""):
    try:
        subprocess.Popen(
            ["notify-send", "-a", "ChatGPT Voice", "-t", "3000", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


class VoiceDaemon:
    def __init__(self, config, visible=False):
        self.config = config
        self.visible = visible
        self.recording = False
        self.page = None
        self.pw = None
        self.context = None
        self.server = None
        self._pre_record_text = ""

    async def find_element(self, selector_list):
        """Try multiple selectors via JS aria-label matching.

        We avoid wait_for_selector(state='visible') because Chromium
        suspends rendering in minimized windows, making elements fail
        visibility checks even though they exist in the DOM.
        """
        import re
        # Extract aria-label keywords from the selectors
        keywords = []
        for sel in selector_list:
            m = re.search(r'aria-label[*~|^$]?=\s*"([^"]+)"', sel)
            if m:
                keywords.append(m.group(1).lower())

        if keywords:
            handle = await self.page.evaluate_handle("""(keywords) => {
                for (const kw of keywords) {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if (label.includes(kw)) return btn;
                    }
                }
                return null;
            }""", keywords)
            el = handle.as_element()
            if el:
                return el

        # Fallback: try CSS selectors with state='attached'
        for selector in selector_list:
            try:
                el = await self.page.wait_for_selector(selector, state="attached", timeout=500)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def start_browser(self):
        from playwright.async_api import async_playwright

        self.pw = await async_playwright().start()
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        self.context = await self.pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            args=launch_args,
            permissions=["microphone"],
            viewport={"width": 1024, "height": 768},
            ignore_default_args=["--enable-automation"],
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        # Override visibility API so recording works when minimized
        await self.page.add_init_script("""
            Object.defineProperty(document, 'visibilityState', {
                get: () => 'visible', configurable: true
            });
            Object.defineProperty(document, 'hidden', {
                get: () => false, configurable: true
            });
            document.addEventListener('visibilitychange', e => e.stopImmediatePropagation(), true);
        """)

        log.info("Navigating to %s", self.config["chatgpt_url"])
        await self.page.goto(self.config["chatgpt_url"], wait_until="domcontentloaded")

        # Wait for the composer to load (ChatGPT is slow to render)
        log.info("Waiting for page to fully render...")
        for _ in range(20):  # up to 20 seconds
            await asyncio.sleep(1)
            has_composer = await self.page.evaluate("""() => {
                return !!document.querySelector('#prompt-textarea')
                    || !!document.querySelector('div[contenteditable="true"]');
            }""")
            if has_composer:
                log.info("Composer loaded")
                break
        else:
            log.warning("Composer not found after 20s, proceeding anyway")

        if not self.visible:
            await self._minimize_window()

        log.info("Browser ready (visible=%s)", self.visible)
        notify("ChatGPT Voice Ready", "Daemon started. Use hotkey to toggle recording.")

    async def _minimize_window(self):
        """Hide browser off-screen instead of minimizing.

        True minimization causes Chromium to suspend the page, breaking
        evaluate() and element queries. Moving off-screen keeps it alive.
        """
        try:
            cdp = await self.page.context.new_cdp_session(self.page)
            window = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {"windowState": "normal"},
                },
            )
            await asyncio.sleep(0.1)
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {"left": -10000, "top": -10000, "width": 800, "height": 600},
                },
            )
            await cdp.detach()
            log.info("Window hidden off-screen")
        except Exception as e:
            log.warning("Could not hide window: %s", e)

    async def _show_window(self):
        """Bring the browser window back on-screen for user interaction."""
        try:
            cdp = await self.page.context.new_cdp_session(self.page)
            window = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {"left": 100, "top": 100, "width": 1024, "height": 768},
                },
            )
            await cdp.detach()
        except Exception as e:
            log.warning("Could not show window: %s", e)

    def _simulate_paste(self):
        """Simulate Ctrl+Shift+V via uinput to paste into focused window."""
        import evdev
        from evdev import ecodes, UInput

        with UInput() as ui:
            # Press Ctrl, Shift, V
            ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
            ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
            ui.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
            ui.syn()
            import time; time.sleep(0.05)
            # Release V, Shift, Ctrl
            ui.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
            ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
            ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
            ui.syn()

    async def _get_input_text(self):
        """Read current text from ChatGPT's input area."""
        return await self.page.evaluate("""
            () => {
                const selectors = ['#prompt-textarea', 'div[contenteditable="true"]', 'textarea'];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const text = (el.innerText || el.value || '').trim();
                        if (text) return text;
                    }
                }
                return '';
            }
        """)

    async def _clear_input(self):
        """Clear ChatGPT's input area."""
        await self.page.evaluate("""
            () => {
                const el = document.querySelector('#prompt-textarea')
                         || document.querySelector('div[contenteditable="true"]');
                if (el) {
                    if (el.tagName === 'TEXTAREA') {
                        el.value = '';
                    } else {
                        el.innerHTML = '<p><br></p>';
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }
        """)

    async def toggle(self):
        """Toggle recording on/off."""
        if not self.recording:
            return await self.start_recording()
        else:
            return await self.stop_recording()

    async def start_recording(self):
        log.info("Starting recording...")

        # Save any existing text and clear
        self._pre_record_text = await self._get_input_text()
        if self._pre_record_text:
            await self._clear_input()
            await asyncio.sleep(0.3)

        mic = await self.find_element(self.config["selectors"]["mic_button"])
        if not mic:
            # Check if we need to log in
            needs_login = await self.page.evaluate("""() => {
                return !!document.querySelector('[data-testid="login-button"]')
                    || !!document.querySelector('button[data-action="click:login"]')
                    || document.body.innerText.includes('Log in')
                       && !document.querySelector('button[aria-label*="Dictate" i]');
            }""")
            if needs_login:
                log.warning("ChatGPT session expired, showing browser for re-login")
                notify("Session expired", "Opening browser to re-login to ChatGPT...")
                await self._show_window()
                return {"status": "login_required"}
            msg = "Could not find microphone button. ChatGPT UI may have changed."
            log.error(msg)
            notify("Error", msg)
            return {"status": "error", "message": msg}

        await mic.click()
        self.recording = True
        log.info("Recording started")
        notify("Recording...", "Speak now. Press hotkey again to stop.")
        return {"status": "recording"}

    async def stop_recording(self):
        log.info("Stopping recording...")

        # Click stop button
        stop = await self.find_element(self.config["selectors"]["stop_button"])
        if stop:
            await stop.click()
            log.info("Clicked stop button")
        else:
            log.warning("No stop button found, trying mic button as toggle")
            mic = await self.find_element(self.config["selectors"]["mic_button"])
            if mic:
                await mic.click()

        self.recording = False

        # Poll for transcribed text
        interval = self.config["post_stop_poll_interval_ms"] / 1000
        timeout = self.config["post_stop_poll_timeout_ms"] / 1000
        elapsed = 0.0
        text = ""

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            text = await self._get_input_text()
            if text and text != self._pre_record_text:
                break

        if text:
            subprocess.run(["wl-copy", "--", text], check=True, timeout=5)
            log.info("Copied transcription to clipboard (len=%d)", len(text))

            # Try to paste into the focused window via uinput
            pasted = False
            try:
                await asyncio.sleep(0.05)
                self._simulate_paste()
                pasted = True
                log.info("Pasted into focused window")
            except Exception as e:
                log.info("Could not auto-paste: %s", e)

            if pasted:
                notify("Pasted!", "Transcription pasted.")
            else:
                notify("Copied!", "Transcription copied to clipboard.")
            # Clear input for next use
            await self._clear_input()
            return {"status": "ok", "text": text, "pasted": pasted}
        else:
            log.warning("No transcription text captured")
            notify("No text captured", "Try speaking louder or longer.")
            return {"status": "empty"}

    async def handle_client(self, reader, writer):
        try:
            data = await asyncio.wait_for(reader.read(256), timeout=5)
            cmd = data.decode().strip()
            log.info("Received command: %s", cmd)

            if cmd == "toggle":
                result = await self.toggle()
                # Do not expose transcript text over local IPC.
                safe_result = {k: v for k, v in result.items() if k != "text"}
                writer.write(json.dumps(safe_result).encode() + b"\n")
            elif cmd == "status":
                state = "recording" if self.recording else "idle"
                writer.write(json.dumps({"status": state}).encode() + b"\n")
            elif cmd == "quit":
                writer.write(b'{"status":"bye"}\n')
                await writer.drain()
                writer.close()
                asyncio.get_event_loop().stop()
                return
            else:
                writer.write(b'{"status":"unknown_command"}\n')

            await writer.drain()
        except Exception as e:
            log.error("Client handler error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def run(self):
        # Clean up stale socket
        Path(SOCKET_PATH).unlink(missing_ok=True)

        await self.start_browser()

        self.server = await asyncio.start_unix_server(
            self.handle_client, path=SOCKET_PATH
        )
        os.chmod(SOCKET_PATH, 0o600)
        Path(PID_FILE).write_text(str(os.getpid()))

        log.info("Listening on %s (PID %d)", SOCKET_PATH, os.getpid())

        # Handle shutdown signals
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self.shutdown()))

        async with self.server:
            await self.server.serve_forever()

    async def shutdown(self):
        log.info("Shutting down...")
        notify("ChatGPT Voice", "Daemon stopping.")
        if self.server:
            self.server.close()
        if self.context:
            await self.context.close()
        if self.pw:
            await self.pw.stop()
        Path(PID_FILE).unlink(missing_ok=True)
        Path(SOCKET_PATH).unlink(missing_ok=True)
        asyncio.get_event_loop().stop()


def send_command(cmd):
    """Send a command to a running daemon."""
    import socket

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(SOCKET_PATH)
        sock.send(cmd.encode())
        response = sock.recv(4096).decode().strip()
        return response
    except ConnectionRefusedError:
        return None
    except FileNotFoundError:
        return None
    finally:
        sock.close()


def is_daemon_running():
    if not Path(PID_FILE).exists():
        return False
    pid = int(Path(PID_FILE).read_text().strip())
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        Path(PID_FILE).unlink(missing_ok=True)
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: daemon.py {start|login|stop|status|toggle}")
        sys.exit(1)

    cmd = sys.argv[1]
    config = load_config()

    if cmd == "start":
        if is_daemon_running():
            print("Daemon already running.")
            sys.exit(0)
        daemon = VoiceDaemon(config, visible=False)
        asyncio.run(daemon.run())

    elif cmd == "login":
        if is_daemon_running():
            print("Stop the daemon first: daemon.py stop")
            sys.exit(1)
        print("Opening browser for login. Log in to ChatGPT, then close the browser.")
        daemon = VoiceDaemon(config, visible=True)
        asyncio.run(daemon.run())

    elif cmd == "stop":
        if is_daemon_running():
            resp = send_command("quit")
            print(resp or "Sent quit signal.")
        else:
            print("Daemon not running.")

    elif cmd == "status":
        if is_daemon_running():
            resp = send_command("status")
            print(resp or "No response.")
        else:
            print("Daemon not running.")

    elif cmd == "toggle":
        if not is_daemon_running():
            print("Daemon not running. Start it first: daemon.py start")
            sys.exit(1)
        resp = send_command("toggle")
        print(resp or "No response.")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
