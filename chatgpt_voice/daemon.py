"""Core VoiceDaemon — platform-agnostic Playwright/ChatGPT logic."""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import signal
import subprocess
import sys

from . import ipc, platform_utils
from .config import data_dir, get_provider_config, load_config, profile_dir

log = logging.getLogger("chatgpt-voice")


class VoiceDaemon:
    def __init__(self, config: dict, visible: bool = False):
        self.config = config
        self.provider = get_provider_config(config)
        self.provider_id = self.provider["id"]
        self.diagnostics_enabled = bool(
            config.get("diagnostics", {}).get("enabled", False)
        )
        self.visible = visible
        self.recording = False
        self.processing = False
        self.recovering = False
        self.page = None
        self.pw = None
        self.context = None
        self.server = None
        self._pre_record_text = ""
        self._shutdown_event: asyncio.Event | None = None
        self._hotkey_listener = None
        self._toggle_lock = asyncio.Lock()
        self._late_recovery_task: asyncio.Task | None = None
        self._session_counter = 0
        self._last_page_state: str = "unknown"

    def _apply_config(self, config: dict) -> None:
        self.config = config
        self.provider = get_provider_config(config)
        self.provider_id = self.provider["id"]
        self.diagnostics_enabled = bool(
            config.get("diagnostics", {}).get("enabled", False)
        )
        logging.getLogger().setLevel(
            logging.DEBUG if self.diagnostics_enabled else logging.INFO
        )

    def _provider_name(self) -> str:
        return self.provider.get("name", self.provider_id)

    def _provider_url(self) -> str:
        return self.provider.get("url", "https://chatgpt.com/")

    def _provider_selectors(self, group: str) -> list[str]:
        selectors = self.provider.get("selectors", {}).get(group, [])
        return [s for s in selectors if isinstance(s, str) and s.strip()]

    def _provider_keywords(self, group: str) -> list[str]:
        import re

        keywords: list[str] = []
        for keyword in self.provider.get("keywords", {}).get(group, []):
            if isinstance(keyword, str) and keyword.strip():
                keywords.append(keyword.strip().lower())
        for selector in self._provider_selectors(group):
            m = re.search(r'aria-label[*~|^$]?=\s*"([^"]+)"', selector)
            if m:
                keywords.append(m.group(1).strip().lower())

        merged: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            if keyword and keyword not in seen:
                merged.append(keyword)
                seen.add(keyword)
        return merged

    def _ignored_button_label_prefixes(self) -> list[str]:
        return [
            "more options for",
            "open conversation options for",
            "pin ",
            "unpin ",
            "open project home",
            "open project options for",
            "open notebook actions",
        ]

    async def _query_any_selector(self, selectors: list[str]) -> bool:
        return await self.page.evaluate("""(selectors) => {
            for (const selector of selectors) {
                try {
                    if (document.querySelector(selector)) return true;
                } catch (_) {}
            }
            return false;
        }""", selectors)

    async def _has_input_area(self) -> bool:
        return await self._query_any_selector(self._provider_selectors("input_area"))

    async def _is_login_required(self) -> bool:
        selectors = self._provider_selectors("login_indicator")
        keywords = self._provider_keywords("login")
        input_selectors = self._provider_selectors("input_area")
        mic_selectors = self._provider_selectors("mic_button")
        return await self.page.evaluate("""({ selectors, keywords, inputSelectors, micSelectors }) => {
            const hasProviderUi = (uiSelectors) => {
                for (const selector of uiSelectors) {
                    try {
                        if (document.querySelector(selector)) return true;
                    } catch (_) {}
                }
                return false;
            };
            if (hasProviderUi(inputSelectors) || hasProviderUi(micSelectors)) {
                return false;
            }
            for (const selector of selectors) {
                try {
                    if (document.querySelector(selector)) return true;
                } catch (_) {}
            }
            const bodyText = (document.body.innerText || '').toLowerCase();
            return keywords.some(keyword => bodyText.includes(keyword));
        }""", {
            "selectors": selectors,
            "keywords": keywords,
            "inputSelectors": input_selectors,
            "micSelectors": mic_selectors,
        })

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

        # Try get_by_role first — matches accessible name (aria-label OR innerText)
        for kw in keywords:
            try:
                locator = self.page.get_by_role("button", name=kw)
                el = await locator.first.element_handle(timeout=500)
                if el:
                    return el
            except Exception:
                continue

        # Try query_selector — works reliably in minimized windows
        for selector in selector_list:
            try:
                el = await self.page.query_selector(selector)
                if el:
                    return el
            except Exception:
                continue

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

        # Fallback: wait up to 3s for any selector to appear
        for selector in selector_list:
            try:
                el = await self.page.wait_for_selector(
                    selector, state="attached", timeout=3000,
                )
                if el:
                    return el
            except Exception:
                continue

        return None

    async def _click_provider_button(self, group: str) -> str | None:
        selectors = self._provider_selectors(group)
        keywords = self._provider_keywords(group)
        return await self.page.evaluate("""({ selectors, keywords, group, ignoredLabelPrefixes }) => {
            const labelFor = (button) => (button.getAttribute('aria-label') || button.innerText || '').trim();
            const isControlLabel = (label) => {
                const lower = label.toLowerCase();
                return !!label
                    && label.length <= 80
                    && !ignoredLabelPrefixes.some(prefix => lower.startsWith(prefix))
                    && !lower.includes('\\n');
            };
            const matchesKeyword = (label, keyword) => {
                const lower = label.toLowerCase();
                if (!isControlLabel(label)) return false;
                if (group === 'stop_button' && keyword === 'stop') {
                    return lower === 'stop'
                        || lower.includes('stop listening')
                        || lower.includes('stop recording')
                        || lower.includes('stop speaking')
                        || lower.includes('submit dictation');
                }
                if (group === 'mic_button') {
                    return lower.includes(keyword)
                        && !lower.includes('stop')
                        && !lower.includes('submit');
                }
                return lower.includes(keyword);
            };
            const usableButton = (el) => {
                const button = el.tagName === 'BUTTON' ? el : el.closest('button');
                if (!button || button.disabled) return null;
                const label = labelFor(button);
                return isControlLabel(label) ? { button, label } : null;
            };
            for (const selector of selectors) {
                try {
                    for (const el of document.querySelectorAll(selector)) {
                        const usable = usableButton(el);
                        if (usable) {
                            usable.button.click();
                            return usable.label || selector;
                        }
                    }
                } catch (_) {}
            }
            for (const keyword of keywords) {
                for (const button of document.querySelectorAll('button')) {
                    const label = labelFor(button);
                    if (matchesKeyword(label, keyword)) {
                        button.click();
                        return label || keyword;
                    }
                }
            }
            return null;
        }""", {
            "selectors": selectors,
            "keywords": keywords,
            "group": group,
            "ignoredLabelPrefixes": self._ignored_button_label_prefixes(),
        })

    async def _provider_button_exists(self, group: str) -> bool:
        selectors = self._provider_selectors(group)
        keywords = self._provider_keywords(group)
        found = await self.page.evaluate("""({ selectors, keywords, group, ignoredLabelPrefixes }) => {
            const labelFor = (button) => (button.getAttribute('aria-label') || button.innerText || '').trim();
            const isControlLabel = (label) => {
                const lower = label.toLowerCase();
                return !!label
                    && label.length <= 80
                    && !ignoredLabelPrefixes.some(prefix => lower.startsWith(prefix))
                    && !lower.includes('\\n');
            };
            const matchesKeyword = (label, keyword) => {
                const lower = label.toLowerCase();
                if (!isControlLabel(label)) return false;
                if (group === 'stop_button' && keyword === 'stop') {
                    return lower === 'stop'
                        || lower.includes('stop listening')
                        || lower.includes('stop recording')
                        || lower.includes('stop speaking')
                        || lower.includes('submit dictation');
                }
                if (group === 'mic_button') {
                    return lower.includes(keyword)
                        && !lower.includes('stop')
                        && !lower.includes('submit');
                }
                return lower.includes(keyword);
            };
            for (const selector of selectors) {
                try {
                    for (const el of document.querySelectorAll(selector)) {
                        const button = el.tagName === 'BUTTON' ? el : el.closest('button');
                        if (button && !button.disabled && isControlLabel(labelFor(button))) return true;
                    }
                } catch (_) {}
            }
            return Array.from(document.querySelectorAll('button'))
                .some(button => keywords.some(keyword => matchesKeyword(labelFor(button), keyword)));
        }""", {
            "selectors": selectors,
            "keywords": keywords,
            "group": group,
            "ignoredLabelPrefixes": self._ignored_button_label_prefixes(),
        })
        return bool(found)

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

        log.info(
            "Navigating to %s provider at %s",
            self._provider_name(),
            self._provider_url(),
        )
        # Retry transient network errors at login: DNS / NIC / VPN may not be
        # ready yet when the daemon starts. Backoff caps at ~60s total.
        transient_markers = (
            "ERR_NAME_NOT_RESOLVED",
            "ERR_INTERNET_DISCONNECTED",
            "ERR_NETWORK_CHANGED",
            "ERR_CONNECTION_RESET",
            "ERR_CONNECTION_REFUSED",
            "ERR_CONNECTION_TIMED_OUT",
            "ERR_PROXY_CONNECTION_FAILED",
            "ERR_NETWORK_IO_SUSPENDED",
            "ERR_ADDRESS_UNREACHABLE",
            "ERR_TIMED_OUT",
        )
        delay = 1.0
        last_error = None
        for attempt in range(8):
            try:
                await self.page.goto(
                    self._provider_url(), wait_until="domcontentloaded",
                )
                last_error = None
                break
            except Exception as e:
                msg = str(e)
                if not any(m in msg for m in transient_markers):
                    raise
                last_error = e
                log.warning(
                    "Transient navigation error (attempt %d): %s; retrying in %.1fs",
                    attempt + 1, msg.splitlines()[0], delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 16.0)
        if last_error is not None:
            log.error("Giving up after retries: %s", last_error)
            raise last_error

        # Wait for the composer to load (ChatGPT is slow to render)
        log.info("Waiting for page to fully render...")
        for _ in range(20):  # up to 20 seconds
            await asyncio.sleep(1)
            has_composer = await self._has_input_area()
            if has_composer:
                log.info("%s composer loaded", self._provider_name())
                break
        else:
            log.warning("%s composer not found after 20s, proceeding anyway", self._provider_name())

        # Dismiss any modal overlays (voice picker, announcements, etc.)
        await self._dismiss_modals()

        if not self.visible:
            await self._minimize_window()

        log.info("Browser ready (visible=%s)", self.visible)
        platform_utils.send_notification(
            "ChatGPT Voice Ready",
            f"{self._provider_name()} provider ready. Use hotkey to toggle recording.",
            timeout=1,
        )

    async def _minimize_window(self):
        """Minimize the Chromium window via CDP windowState=minimized.

        The page has a visibility override script injected so that
        page.evaluate() and wait_for_selector() still work when minimized.
        """
        try:
            cdp = await self.page.context.new_cdp_session(self.page)
            window = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {"windowState": "minimized"},
                },
            )
            await cdp.detach()
            log.info("Window minimized via CDP")
        except Exception as e:
            log.warning("Could not minimize window via CDP: %s", e)

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

            await self.page.goto(self._provider_url(), wait_until="domcontentloaded")
            for _ in range(20):
                await asyncio.sleep(1)
                has_composer = await self._has_input_area()
                if has_composer:
                    break
            await self._dismiss_modals()

            if not self.visible:
                await self._minimize_window()

            log.info("Page recovered successfully")
        except Exception as e:
            log.error("Failed to recover page: %s", e)
            raise

    async def _get_page_voice_state(self) -> dict:
        """Return the provider page's observed dictation state.

        The daemon's internal state is useful for sequencing, but the page is
        the authority for whether dictation actually started.
        """
        try:
            state = await self.page.evaluate("""
                ({ inputSelectors, micSelectors, stopSelectors, micKeywords, stopKeywords, recordingKeywords, processingKeywords, ignoredLabelPrefixes }) => {
                    const buttonLabel = (button) => (button.getAttribute('aria-label') || button.innerText || '').trim();
                    const isControlLabel = (label) => {
                        const lower = label.toLowerCase();
                        return !!label
                            && label.length <= 80
                            && !ignoredLabelPrefixes.some(prefix => lower.startsWith(prefix))
                            && !lower.includes('\\n');
                    };
                    const matchesKeyword = (label, keyword, group) => {
                        const lower = label.toLowerCase();
                        if (!isControlLabel(label)) return false;
                        if (group === 'stop' && keyword === 'stop') {
                            return lower === 'stop'
                                || lower.includes('stop listening')
                                || lower.includes('stop recording')
                                || lower.includes('stop speaking')
                                || lower.includes('submit dictation');
                        }
                        return lower.includes(keyword);
                    };
                    const matchesButtonSelector = (selectors) => {
                        for (const selector of selectors) {
                            try {
                                const buttons = Array.from(document.querySelectorAll(selector))
                                    .filter(el => el.tagName === 'BUTTON' || el.closest('button'))
                                    .map(el => el.tagName === 'BUTTON' ? el : el.closest('button'));
                                if (buttons.some(button => isControlLabel(buttonLabel(button)))) return true;
                            } catch (_) {}
                        }
                        return false;
                    };
                    const firstInput = () => {
                        for (const selector of inputSelectors) {
                            try {
                                const el = document.querySelector(selector);
                                if (el) return el;
                            } catch (_) {}
                        }
                        return null;
                    };
                    const labels = Array.from(document.querySelectorAll('button'))
                        .map(b => (b.getAttribute('aria-label') || b.innerText || '').trim())
                        .filter(Boolean);
                    const controlLabels = labels.filter(isControlLabel);
                    const lower = controlLabels.map(label => label.toLowerCase());
                    const busyNodes = Array.from(document.querySelectorAll('[aria-busy="true"], [role="progressbar"], [data-state="loading"]'));
                    const hasStop = matchesButtonSelector(stopSelectors)
                        || controlLabels.some(label => stopKeywords.some(keyword => matchesKeyword(label, keyword, 'stop')));
                    const hasStart = matchesButtonSelector(micSelectors)
                        || lower.some(label =>
                            micKeywords.some(keyword => label.includes(keyword))
                            && !label.includes('stop')
                            && !label.includes('submit')
                        );
                    const hasRecording = lower.some(label =>
                        recordingKeywords.some(keyword => matchesKeyword(label, keyword, 'recording'))
                    );
                    const hasProcessing = (busyNodes.length > 0 && !hasStart)
                        || lower.some(label => processingKeywords.some(keyword => label.includes(keyword)));
                    const input = firstInput();
                    const hasComposer = !!input;
                    let text = '';
                    if (input) text = (input.innerText || input.value || '').trim();
                    let observed = 'unknown';
                    if (hasStop || hasRecording) observed = 'recording';
                    else if (hasProcessing) observed = 'processing';
                    else if (hasStart || hasComposer) observed = 'idle';
                    return {
                        observed,
                        hasStart,
                        hasStop,
                        hasProcessing,
                        hasComposer,
                        textLength: text.length,
                        labels: controlLabels.slice(0, 50),
                    };
                }
            """, {
                "inputSelectors": self._provider_selectors("input_area"),
                "micSelectors": self._provider_selectors("mic_button"),
                "stopSelectors": self._provider_selectors("stop_button"),
                "micKeywords": self._provider_keywords("mic_button"),
                "stopKeywords": self._provider_keywords("stop_button"),
                "recordingKeywords": self._provider_keywords("recording"),
                "processingKeywords": self._provider_keywords("processing"),
                "ignoredLabelPrefixes": self._ignored_button_label_prefixes(),
            })
            self._last_page_state = state.get("observed", "unknown")
            if self.diagnostics_enabled:
                log.debug("Observed provider state: %s", state)
            return state
        except Exception as e:
            log.warning("Could not observe page dictation state: %s", e)
            self._last_page_state = "unavailable"
            return {
                "observed": "unavailable",
                "hasStart": False,
                "hasStop": False,
                "hasProcessing": False,
                "hasComposer": False,
                "textLength": 0,
                "labels": [],
                "error": str(e),
            }

    async def _wait_for_page_voice_state(self, expected: str, timeout: float = 4.0) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        state = await self._get_page_voice_state()
        while state.get("observed") != expected and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.2)
            state = await self._get_page_voice_state()
        return state

    def _is_idle_without_text(self, state: dict) -> bool:
        return (
            state.get("observed") == "idle"
            and state.get("textLength", 0) == 0
            and not state.get("hasProcessing")
        )

    async def _cancel_late_recovery(self, reason: str) -> None:
        task = self._late_recovery_task
        self.recovering = False
        self._late_recovery_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        log.info("Cancelled late transcription recovery: %s", reason)

    async def _status_state(self) -> str:
        if self.recording:
            observed = await self._get_page_voice_state()
            if observed.get("observed") != "recording":
                log.warning(
                    "Internal recording state disagrees with page state (%s); resetting to idle",
                    observed.get("observed"),
                )
                self.recording = False
                return "idle"
            return "recording"
        if self.processing:
            observed = await self._get_page_voice_state()
            if observed.get("observed") == "unavailable":
                log.warning("Processing page is unavailable; resetting to idle")
                self.processing = False
                return "idle"
            if observed.get("observed") == "processing":
                return "processing"
            return "processing"
        if self.recovering:
            observed = await self._get_page_voice_state()
            if observed.get("observed") == "recording":
                log.warning("Recovery state disagrees with page recording state; reporting recording")
                await self._cancel_late_recovery("page is recording")
                self.recording = True
                return "recording"
            if self._is_idle_without_text(observed):
                log.warning("Recovery state ended because provider is idle with no text")
                await self._cancel_late_recovery("provider idle with no text")
                return "idle"
            return "recovering"
        if self.page:
            observed = await self._get_page_voice_state()
            if observed.get("observed") == "recording":
                log.warning("Idle internal state disagrees with page recording state; reporting recording")
                self.recording = True
                return "recording"
        return "idle"

    def _quick_status_state(self) -> str:
        if self.recording:
            return "recording"
        if self.processing:
            return "processing"
        if self.recovering:
            return "recovering"
        return "idle"

    # ------------------------------------------------------------------
    # Input field helpers
    # ------------------------------------------------------------------

    async def _get_input_text(self):
        """Read current text from the provider input area."""
        return await self.page.evaluate("""
            (selectors) => {
                for (const selector of selectors) {
                    try {
                        const el = document.querySelector(selector);
                        if (el) {
                            const text = (el.innerText || el.value || '').trim();
                            if (text) return text;
                        }
                    } catch (_) {}
                }
                return '';
            }
        """, self._provider_selectors("input_area"))

    async def _clear_input(self):
        """Clear the provider input area."""
        await self.page.evaluate("""
            (selectors) => {
                let el = null;
                for (const selector of selectors) {
                    try {
                        el = document.querySelector(selector);
                        if (el) break;
                    } catch (_) {}
                }
                if (el) {
                    if (el.tagName === 'TEXTAREA') {
                        el.value = '';
                    } else {
                        el.textContent = '';
                        el.replaceChildren(document.createElement('br'));
                    }
                    try {
                        el.dispatchEvent(new InputEvent('input', {
                            bubbles: true,
                            inputType: 'deleteContentBackward',
                            data: null
                        }));
                    } catch (_) {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }
            }
        """, self._provider_selectors("input_area"))

    def _recovery_file(self):
        path = data_dir() / "recovered-transcripts.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _save_recovered_transcript(self, text: str, source: str):
        """Append a recovered transcript to a local holding file."""
        now = datetime.now(timezone.utc)
        record = {
            "created_at": now.isoformat(),
            "source": source,
            "length": len(text),
            "text": text,
        }
        with open(self._recovery_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        transcript_dir = data_dir() / "recovered-transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        safe_source = "".join(c if c.isalnum() or c in "-_" else "-" for c in source)
        transcript_file = transcript_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{safe_source}.txt"
        transcript_file.write_text(text, encoding="utf-8")
        return transcript_file

    def _open_recovered_transcript(self, path) -> None:
        """Open recovered text in the user's default editor/viewer."""
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            log.warning("Could not open recovered transcript file %s: %s", path, e)

    async def _capture_late_transcript_if_present(
        self,
        pre_record_text: str,
        source: str,
        clear: bool = True,
    ) -> str:
        """Capture text that arrived after the normal stop path timed out."""
        text = await self._get_input_text()
        if not text or text == pre_record_text:
            return ""

        transcript_file = self._save_recovered_transcript(text, source)
        log.warning(
            "Recovered late transcription to holding files (len=%d, source=%s, file=%s)",
            len(text),
            source,
            transcript_file,
        )
        platform_utils.send_notification(
            "Late transcript recovered",
            "Opening recovered transcript in your text editor.",
            timeout=5,
        )
        self._open_recovered_transcript(transcript_file)
        if clear:
            await self._clear_input()
        return text

    def _transcript_ready_for_capture(
        self,
        text: str,
        pre_record_text: str,
        observed_state: str,
        elapsed: float,
        last_changed_at: float,
        min_wait: float,
        stable_wait: float,
        busy_grace: float,
    ) -> bool:
        if not text or text == pre_record_text:
            return False
        if elapsed < min_wait:
            return False
        if elapsed - last_changed_at < stable_wait:
            return False
        if observed_state in ("recording", "processing") and elapsed < busy_grace:
            return False
        return True

    def _post_stop_delay_ms(self, provider_key: str, legacy_key: str) -> int:
        provider_value = self.provider.get("post_stop", {}).get(provider_key)
        if isinstance(provider_value, (int, float)) and provider_value >= 0:
            return int(provider_value)
        return int(self.config.get(legacy_key, 0))

    def _normalize_transcript_for_compare(self, text: str) -> str:
        return " ".join((text or "").split())

    def _choose_transcript_candidate(
        self,
        current_text: str,
        best_text: str,
        pre_record_text: str,
    ) -> str:
        current_text = current_text or ""
        best_text = best_text or ""
        if not current_text or current_text == pre_record_text:
            return best_text
        if not best_text:
            return current_text

        current_norm = self._normalize_transcript_for_compare(current_text)
        best_norm = self._normalize_transcript_for_compare(best_text)
        if best_norm.startswith(current_norm) and len(best_norm) > len(current_norm):
            return best_text
        if len(current_norm) > len(best_norm):
            return current_text
        return current_text

    async def _poll_for_late_transcript(self, pre_record_text: str, session_id: int):
        interval = self.config.get("late_transcript_poll_interval_ms", 1000) / 1000
        timeout = self.config.get("late_transcript_poll_timeout_ms", 300000) / 1000
        elapsed = 0.0
        self.recovering = True

        log.info(
            "Polling for late transcription after timeout (session=%d, timeout=%.1fs)",
            session_id,
            timeout,
        )
        try:
            while elapsed < timeout:
                await asyncio.sleep(interval)
                elapsed += interval
                await self._ensure_page()
                recovered = await self._capture_late_transcript_if_present(
                    pre_record_text,
                    source=f"late-poll-session-{session_id}",
                )
                if recovered:
                    return
            log.warning("Late transcription did not appear (session=%d)", session_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Late transcription recovery failed (session=%d): %s", session_id, e)
        finally:
            self.recovering = False
            if self._late_recovery_task is asyncio.current_task():
                self._late_recovery_task = None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def toggle(self):
        async with self._toggle_lock:
            if self.recovering:
                observed = await self._get_page_voice_state()
                if observed.get("observed") == "recording":
                    log.warning("Toggle requested during recovery, but provider is recording; stopping it")
                    await self._cancel_late_recovery("toggle found active recording")
                    self.recording = True
                    self.processing = False
                    return await self.stop_recording()
                if self._is_idle_without_text(observed):
                    log.warning("Toggle requested during stale recovery; provider is idle with no text")
                    await self._cancel_late_recovery("toggle found provider idle with no text")
                else:
                    platform_utils.send_notification(
                        "Dictation still processing",
                        f"Wait for {self._provider_name()} to finish before starting another session.",
                        timeout=3,
                    )
                    log.info("Ignoring toggle while recovering previous dictation")
                    return {"status": "recovering"}
            if self.processing:
                status = "processing" if self.processing else "recovering"
                platform_utils.send_notification(
                    "Dictation still processing",
                    f"Wait for {self._provider_name()} to finish before starting another session.",
                    timeout=3,
                )
                log.info("Ignoring toggle while %s previous dictation", status)
                return {"status": status}
            if not self.recording and self.page:
                observed = await self._get_page_voice_state()
                if observed.get("observed") == "recording":
                    log.warning("Toggle requested while provider page is recording but internal state is idle")
                    self.recording = True
                    self.processing = False
                    return await self.stop_recording()
            if not self.recording:
                return await self.start_recording()
            else:
                return await self.stop_recording()

    async def start_recording(self):
        log.info("Starting recording with %s...", self._provider_name())
        await self._ensure_page()

        if self.processing or self.recovering:
            status = "processing" if self.processing else "recovering"
            log.info("Start requested while %s previous dictation", status)
            return {"status": status}

        observed = await self._get_page_voice_state()
        if observed.get("observed") == "recording":
            log.warning("Start requested while provider page is already recording")
            self.recording = True
            return {"status": "recording", "message": "provider already recording"}

        if self._late_recovery_task and not self._late_recovery_task.done():
            self._late_recovery_task.cancel()
            try:
                await self._late_recovery_task
            except asyncio.CancelledError:
                pass
            log.info("Cancelled background late transcription poll before new recording")

        recovered = await self._capture_late_transcript_if_present(
            self._pre_record_text,
            source="pre-start",
        )
        if recovered:
            await asyncio.sleep(0.3)

        self._pre_record_text = await self._get_input_text()
        if self._pre_record_text:
            await self._clear_input()
            await asyncio.sleep(0.3)

        # Poll via JS evaluate — the only method that reliably finds buttons
        # in minimized Chromium windows. Poll for up to 5 seconds.
        clicked = None
        for _i in range(150):  # 150 × 100ms = 15s
            clicked = await self._click_provider_button("mic_button")
            if clicked:
                log.info("Clicked mic button via JS after %d polls (keyword=%s)", _i + 1, clicked)
                break
            await asyncio.sleep(0.1)
        if not clicked:
            mic = await self.find_element(self._provider_selectors("mic_button"))
            if not mic:
                # Check if we need to log in
                needs_login = await self._is_login_required()
                if needs_login:
                    log.warning("%s session expired, showing browser for re-login", self._provider_name())
                    platform_utils.send_notification(
                        "Session expired",
                        f"Opening browser to re-login to {self._provider_name()}...",
                    )
                    await self._show_window()
                    return {"status": "login_required"}
                # Debug: dump all buttons on the page
                try:
                    btns = await self.page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('button'))
                            .map(b => {
                                const al = b.getAttribute('aria-label');
                                const tx = b.innerText.substring(0, 30);
                                return al ? `aria-label="${al}"` : (tx ? `text="${tx}"` : null);
                            })
                            .filter(Boolean);
                    }""")
                    log.error("Mic button not found. Available buttons: %s", btns)
                except Exception:
                    log.error("Mic button not found and could not dump page buttons")
                platform_utils.send_notification(
                    "Error",
                    f"Could not find {self._provider_name()} microphone button.",
                )
                return {"status": "error", "message": "mic button not found"}
            await mic.click()
        else:
            log.info("Clicked mic button via JS (keyword=%s)", clicked)

        observed = await self._wait_for_page_voice_state("recording", timeout=12.0)
        if observed.get("observed") != "recording":
            log.warning(
                "Mic click did not start dictation; page state=%s buttons=%s",
                observed.get("observed"),
                observed.get("labels"),
            )
            self.recording = False
            platform_utils.send_notification(
                "Dictation did not start",
                f"{self._provider_name()} did not enter recording mode.",
                timeout=4,
            )
            return {"status": "not_recording"}

        self.recording = True
        log.info("Recording started")
        platform_utils.send_notification(
            "Recording...", "Speak now. Press hotkey again to stop.",
        )
        return {"status": "recording"}

    async def stop_recording(self):
        log.info("Stopping recording with %s...", self._provider_name())
        await self._ensure_page()
        self._session_counter += 1
        session_id = self._session_counter

        observed_before = await self._get_page_voice_state()
        if observed_before.get("observed") != "recording":
            log.warning(
                "Stop requested, but page is not recording (state=%s buttons=%s)",
                observed_before.get("observed"),
                observed_before.get("labels"),
            )
            self.recording = False
            self.processing = False
            platform_utils.send_notification(
                "Dictation was not active",
                f"{self._provider_name()} is not recording in the background browser.",
                timeout=4,
            )
            return {"status": "not_recording"}

        pre_stop_text = await self._get_input_text()
        clicked = await self._click_provider_button("stop_button")
        if clicked:
            log.info("Clicked stop button (%s)", clicked)
        else:
            log.warning("No stop button found, trying mic button as toggle")
            clicked = await self._click_provider_button("mic_button")
            if clicked:
                log.info("Clicked mic button as stop toggle (%s)", clicked)

        self.recording = False
        self.processing = True

        # Poll for transcribed text
        interval = self.config["post_stop_poll_interval_ms"] / 1000
        timeout = self.config["post_stop_poll_timeout_ms"] / 1000
        idle_no_text_timeout = self.config.get("post_stop_idle_no_text_timeout_ms", 15000) / 1000
        min_wait = self._post_stop_delay_ms("min_wait_ms", "post_stop_min_wait_ms") / 1000
        stable_wait = self._post_stop_delay_ms("text_stable_ms", "post_stop_text_stable_ms") / 1000
        busy_grace = self._post_stop_delay_ms("busy_grace_ms", "post_stop_busy_grace_ms") / 1000
        elapsed = 0.0
        text = pre_stop_text if pre_stop_text and pre_stop_text != self._pre_record_text else ""
        last_text = pre_stop_text
        last_changed_at = 0.0
        no_recovery = False

        try:
            while elapsed < timeout:
                await asyncio.sleep(interval)
                elapsed += interval
                current_text = await self._get_input_text()
                if current_text != last_text:
                    previous_best = text
                    last_text = current_text
                    last_changed_at = elapsed
                    text = self._choose_transcript_candidate(
                        current_text,
                        text,
                        self._pre_record_text,
                    )
                    if text and text != self._pre_record_text and text != previous_best:
                        log.debug(
                            "Transcript candidate changed after stop (elapsed=%.1fs, len=%d, current_len=%d)",
                            elapsed,
                            len(text),
                            len(current_text),
                        )
                observed = await self._get_page_voice_state()
                if self._transcript_ready_for_capture(
                    text=text,
                    pre_record_text=self._pre_record_text,
                    observed_state=observed.get("observed", "unknown"),
                    elapsed=elapsed,
                    last_changed_at=last_changed_at,
                    min_wait=min_wait,
                    stable_wait=stable_wait,
                    busy_grace=busy_grace,
                ):
                    log.info(
                        "Transcript stabilized after stop (elapsed=%.1fs, stable=%.1fs, state=%s, len=%d)",
                        elapsed,
                        elapsed - last_changed_at,
                        observed.get("observed"),
                        len(text),
                    )
                    break
                if (
                    observed.get("observed") == "idle"
                    and observed.get("textLength", 0) == 0
                    and not observed.get("hasProcessing")
                    and elapsed >= idle_no_text_timeout
                ):
                    log.warning(
                        "%s is idle with no text after %.1fs; treating as no active transcription",
                        self._provider_name(),
                        elapsed,
                    )
                    no_recovery = True
                    break
                if observed.get("observed") == "unavailable":
                    log.warning("Page became unavailable while processing; ending processing")
                    no_recovery = True
                    break
        except Exception as e:
            log.error("Processing failed while polling for transcript: %s", e)
            text = ""
            no_recovery = True
        finally:
            self.processing = False

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
            if no_recovery:
                log.warning(
                    "No transcription text captured after %.1fs; not starting late recovery",
                    elapsed,
                )
                platform_utils.send_notification(
                    "No active transcription",
                    f"{self._provider_name()} returned idle without text.",
                    timeout=4,
                )
                return {"status": "empty"}
            log.warning(
                "No transcription text captured after %.1fs; leaving composer intact for late recovery",
                elapsed,
            )
            platform_utils.send_notification(
                "Still waiting for text",
                f"If {self._provider_name()} finishes late, it will open in your text editor.",
            )
            self._late_recovery_task = asyncio.create_task(
                self._poll_for_late_transcript(self._pre_record_text, session_id)
            )
            return {"status": "empty"}

    # ------------------------------------------------------------------
    # Provider diagnostics
    # ------------------------------------------------------------------

    async def reload_config(self) -> dict:
        """Reload config.json and navigate to the selected provider when idle."""
        if self.recording or self.processing or self.recovering:
            return {
                "status": "busy",
                "provider": self.provider_id,
                "message": "Cannot reload provider while dictation is active.",
            }

        old_provider = self.provider_id
        old_url = self._provider_url()
        self._apply_config(load_config())
        new_url = self._provider_url()

        if self.page and (self.provider_id != old_provider or new_url != old_url):
            log.info(
                "Provider changed from %s to %s; navigating to %s",
                old_provider,
                self.provider_id,
                new_url,
            )
            await self.page.goto(new_url, wait_until="domcontentloaded")
            await self._dismiss_modals()
            if not self.visible:
                await self._minimize_window()

        return {
            "status": "ok",
            "provider": self.provider_id,
            "provider_name": self._provider_name(),
            "diagnostics": self.diagnostics_enabled,
        }

    async def test_connection(self) -> dict:
        """Inspect the current provider page without starting recording."""
        await self._ensure_page()
        state = await self._get_page_voice_state()
        login_required = await self._is_login_required()
        mic_found = await self._provider_button_exists("mic_button")
        stop_found = await self._provider_button_exists("stop_button")
        result = {
            "status": "ok",
            "provider": self.provider_id,
            "provider_name": self._provider_name(),
            "url": self._provider_url(),
            "current_url": self.page.url,
            "login_required": login_required,
            "page_state": state.get("observed"),
            "composer_found": state.get("hasComposer", False),
            "mic_found": mic_found,
            "stop_found": stop_found,
            "diagnostics": self.diagnostics_enabled,
        }
        if self.diagnostics_enabled:
            result["button_labels"] = state.get("labels", [])
            log.debug("Connection test result: %s", result)
        return result

    # ------------------------------------------------------------------
    # IPC handler
    # ------------------------------------------------------------------

    async def handle_client(self, reader, writer):
        try:
            data = await asyncio.wait_for(reader.read(256), timeout=5)
            cmd = data.decode().strip()
            if cmd == "status":
                log.debug("Received command: %s", cmd)
            elif cmd == "status_quick":
                pass
            else:
                log.info("Received command: %s", cmd)

            if cmd == "toggle":
                result = await self.toggle()
                # Do not expose transcript text over local IPC.
                safe_result = {k: v for k, v in result.items() if k != "text"}
                writer.write(json.dumps(safe_result).encode() + b"\n")
            elif cmd == "status":
                state = await self._status_state()
                writer.write(json.dumps({
                    "status": state,
                    "provider": self.provider_id,
                    "provider_name": self._provider_name(),
                }).encode() + b"\n")
            elif cmd == "status_quick":
                writer.write(json.dumps({
                    "status": self._quick_status_state(),
                    "provider": self.provider_id,
                    "provider_name": self._provider_name(),
                }).encode() + b"\n")
            elif cmd == "reload_config":
                result = await self.reload_config()
                writer.write(json.dumps(result).encode() + b"\n")
            elif cmd == "test_connection":
                result = await self.test_connection()
                writer.write(json.dumps(result).encode() + b"\n")
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

        self.server = await ipc.start_server(self.handle_client)
        ipc.write_pid()

        tick_task = None
        try:
            await self.start_browser()

            log.info("Daemon running (PID %d)", __import__("os").getpid())

            loop = asyncio.get_running_loop()

            # Handle shutdown signals so Ctrl+C runs the cleanup path (close
            # Chromium, drop PID file, stop hotkey listener) instead of dumping
            # a KeyboardInterrupt traceback.
            if sys.platform == "win32":
                # On Windows asyncio's ProactorEventLoop ignores add_signal_handler.
                # Use signal.signal() + a periodic wakeup so the handler runs while
                # we're suspended on _shutdown_event.wait().
                def _win_sig(_sig, _frame):
                    loop.call_soon_threadsafe(self._shutdown_event.set)
                for _s in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
                    if _s is not None:
                        try:
                            signal.signal(_s, _win_sig)
                        except (ValueError, OSError):
                            pass

                async def _tick():
                    while not self._shutdown_event.is_set():
                        await asyncio.sleep(0.25)
                tick_task = asyncio.create_task(_tick())
            else:
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, self._shutdown_event.set)

            # Register global hotkey (non-Wayland platforms).
            # Capture the running loop here (main thread); the callback runs in pynput's
            # thread and must schedule the coroutine on this loop, not get_event_loop().
            hotkey_combo = self.config.get("hotkey", "ctrl+shift+.")

            def _make_hotkey_handler(coro_func):
                def handler():
                    fut = asyncio.run_coroutine_threadsafe(coro_func(), loop)
                    def _log_exc(f):
                        if not f.cancelled() and f.exception():
                            log.error("Hotkey handler error: %s", f.exception(), exc_info=f.exception())
                    fut.add_done_callback(_log_exc)
                return handler

            self._hotkey_listener = platform_utils.register_global_hotkey(
                hotkey_combo,
                _make_hotkey_handler(self.toggle),
            )
            if self._hotkey_listener:
                log.info("Global hotkey registered: %s", hotkey_combo)

            await self._shutdown_event.wait()
        finally:
            if tick_task is not None:
                tick_task.cancel()
            await self.shutdown()

    async def shutdown(self):
        log.info("Shutting down...")
        platform_utils.send_notification("ChatGPT Voice", "Daemon stopping.")

        if self._hotkey_listener:
            self._hotkey_listener.stop()
            self._hotkey_listener = None

        if self._late_recovery_task:
            self._late_recovery_task.cancel()
            try:
                await self._late_recovery_task
            except asyncio.CancelledError:
                pass
            self._late_recovery_task = None

        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.context:
            await self.context.close()
        if self.pw:
            await self.pw.stop()

        ipc.cleanup()
