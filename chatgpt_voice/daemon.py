"""Core VoiceDaemon — platform-agnostic Playwright/ChatGPT logic."""

import asyncio
import json
import logging
import signal
import sys

from . import ipc, platform_utils
from .config import load_config, profile_dir

log = logging.getLogger("chatgpt-voice")


class VoiceDaemon:
    def __init__(self, config: dict, visible: bool = False):
        self.config = config
        self.visible = visible
        self.recording = False
        self.page = None
        self.pw = None
        self.context = None
        self.server = None
        self._pre_record_text = ""
        self._shutdown_event: asyncio.Event | None = None
        self._hotkey_listener = None

    # ------------------------------------------------------------------
    # Browser helpers
    # ------------------------------------------------------------------

    async def find_element(self, selector_list):
        """Try multiple selectors via JS aria-label matching first.

        We prioritize JS-based search because Chromium suspends rendering
        in off-screen/minimized windows, making CSS visibility checks
        unreliable. Falls back to CSS selectors with state='attached'.
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
                el = await self.page.wait_for_selector(
                    selector, state="attached", timeout=500,
                )
                if el:
                    return el
            except Exception:
                continue

        return None

    async def start_browser(self):
        from playwright.async_api import async_playwright

        self.pw = await async_playwright().start()
        pdir = profile_dir()
        pdir.mkdir(parents=True, exist_ok=True)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        self.context = await self.pw.chromium.launch_persistent_context(
            str(pdir),
            headless=False,
            args=launch_args,
            permissions=["microphone"],
            viewport={"width": 1024, "height": 768},
            ignore_default_args=["--enable-automation"],
        )

        self.page = (
            self.context.pages[0]
            if self.context.pages
            else await self.context.new_page()
        )

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
        await self.page.goto(
            self.config["chatgpt_url"], wait_until="domcontentloaded",
        )

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

        # Dismiss any modal overlays (voice picker, announcements, etc.)
        await self._dismiss_modals()

        if not self.visible:
            await self._minimize_window()

        log.info("Browser ready (visible=%s)", self.visible)
        platform_utils.send_notification(
            "ChatGPT Voice Ready",
            "Daemon started. Use hotkey to toggle recording.",
            timeout=1,
        )

    async def _minimize_window(self):
        """Hide the Chromium window by making it tiny and off-screen.

        We avoid true minimization because Chromium suspends/freezes pages
        in minimized windows, which breaks page.evaluate() and
        wait_for_selector().
        """
        try:
            cdp = await self.page.context.new_cdp_session(self.page)
            window = await cdp.send("Browser.getWindowForTarget")
            # First ensure it's in "normal" state (not maximized)
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {"windowState": "normal"},
                },
            )
            await asyncio.sleep(0.1)
            # Then make it tiny and move it far off-screen
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {
                        "left": -10000,
                        "top": -10000,
                        "width": 800,
                        "height": 600,
                    },
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

    async def _dismiss_modals(self):
        """Close any modal overlays that might intercept clicks."""
        # Dismiss voice picker modal
        try:
            modal = await self.page.query_selector('[data-testid="modal-voice-picker"]')
            if modal:
                log.info("Voice picker modal detected, dismissing...")
                # Press Escape to close it
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Dismiss any generic close/dismiss buttons on overlays
        for selector in [
            'button[aria-label="Close" i]',
            'button[aria-label="Dismiss" i]',
            '[data-testid="modal-voice-picker"] button',
        ]:
            try:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.3)
                    log.info("Dismissed overlay via %s", selector)
            except Exception:
                continue

    async def _ensure_page(self):
        """Make sure the page is alive. Re-navigate if it crashed."""
        try:
            await self.page.evaluate("1")
            return
        except Exception:
            log.warning("Page is dead, recovering...")

        try:
            # Try to get an existing page or create a new one
            if self.context.pages:
                self.page = self.context.pages[0]
                try:
                    await self.page.evaluate("1")
                except Exception:
                    self.page = await self.context.new_page()
            else:
                self.page = await self.context.new_page()

            # Re-inject visibility override
            await self.page.add_init_script("""
                Object.defineProperty(document, 'visibilityState', {
                    get: () => 'visible', configurable: true
                });
                Object.defineProperty(document, 'hidden', {
                    get: () => false, configurable: true
                });
                document.addEventListener('visibilitychange', e => e.stopImmediatePropagation(), true);
            """)

            await self.page.goto(
                self.config["chatgpt_url"], wait_until="domcontentloaded",
            )
            for _ in range(20):
                await asyncio.sleep(1)
                has_composer = await self.page.evaluate("""() => {
                    return !!document.querySelector('#prompt-textarea')
                        || !!document.querySelector('div[contenteditable="true"]');
                }""")
                if has_composer:
                    break
            await self._dismiss_modals()

            if not self.visible:
                await self._minimize_window()

            log.info("Page recovered successfully")
        except Exception as e:
            log.error("Failed to recover page: %s", e)
            raise

    # ------------------------------------------------------------------
    # Input field helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def toggle(self):
        if not self.recording:
            return await self.start_recording()
        else:
            return await self.stop_recording()

    async def start_recording(self):
        log.info("Starting recording...")
        await self._ensure_page()
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
                platform_utils.send_notification(
                    "Session expired",
                    "Opening browser to re-login to ChatGPT...",
                )
                await self._show_window()
                return {"status": "login_required"}
            # Debug: avoid logging button labels (can include sensitive UI text)
            try:
                btns = await self.page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('button'))
                        .map(b => b.getAttribute('aria-label') || b.innerText.substring(0, 30) || '(no label)')
                        .filter(l => l !== '(no label)');
                }""")
                log.error("Mic button not found. Found %d labeled buttons.", len(btns))
            except Exception:
                log.error("Mic button not found and could not dump page buttons")
            platform_utils.send_notification("Error", "Could not find microphone button.")
            return {"status": "error", "message": "mic button not found"}

        await mic.click()
        self.recording = True
        log.info("Recording started")
        platform_utils.send_notification(
            "Recording...", "Speak now. Press hotkey again to stop.",
        )
        return {"status": "recording"}

    async def stop_recording(self):
        log.info("Stopping recording...")
        await self._ensure_page()

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
            platform_utils.copy_to_clipboard(text)
            log.info("Copied transcription to clipboard (len=%d)", len(text))

            pasted = False
            try:
                await asyncio.sleep(0.05)
                platform_utils.simulate_paste()
                pasted = True
                log.info("Pasted into focused window")
            except Exception as e:
                log.info("Could not auto-paste: %s", e)

            await self._clear_input()
            return {"status": "ok", "text": text, "pasted": pasted}
        else:
            log.warning("No transcription text captured")
            platform_utils.send_notification(
                "No text captured", "Try speaking louder or longer.",
            )
            return {"status": "empty"}

    # ------------------------------------------------------------------
    # IPC handler
    # ------------------------------------------------------------------

    async def handle_client(self, reader, writer):
        try:
            data = await asyncio.wait_for(reader.read(256), timeout=5)
            cmd = data.decode().strip()
            if cmd == "status":
                log.debug("Received command: %s", cmd)
            else:
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
                self._shutdown_event.set()
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

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self):
        self._shutdown_event = asyncio.Event()

        await self.start_browser()

        self.server = await ipc.start_server(self.handle_client)
        ipc.write_pid()

        log.info("Daemon running (PID %d)", __import__("os").getpid())

        # Handle shutdown signals (Unix only)
        if sys.platform != "win32":
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._shutdown_event.set)

        # Register global hotkey (non-Wayland platforms).
        # Capture the running loop here (main thread); the callback runs in pynput's
        # thread and must schedule the coroutine on this loop, not get_event_loop().
        loop = asyncio.get_running_loop()
        hotkey_combo = self.config.get("hotkey", "ctrl+shift+.")
        self._hotkey_listener = platform_utils.register_global_hotkey(
            hotkey_combo,
            lambda: asyncio.run_coroutine_threadsafe(self.toggle(), loop),
        )
        if self._hotkey_listener:
            log.info("Global hotkey registered: %s", hotkey_combo)

        # Wait for shutdown signal
        await self._shutdown_event.wait()
        await self.shutdown()

    async def shutdown(self):
        log.info("Shutting down...")
        platform_utils.send_notification("ChatGPT Voice", "Daemon stopping.")

        if self._hotkey_listener:
            self._hotkey_listener.stop()
            self._hotkey_listener = None

        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.context:
            await self.context.close()
        if self.pw:
            await self.pw.stop()

        ipc.cleanup()
