# Bug: "Could not find microphone button" on recording trigger

## Symptom
Pressing the hotkey (Ctrl+Shift+.) triggers `start_recording()` but fails with:
> Could not find microphone button.

## Root Cause Analysis (ongoing)

### Finding 1 — ChatGPT renamed the button (2026-03-31)
- Old aria-label: `"Dictate button"`
- New aria-label: `"Start dictation"`
- Confirmed by user pasting the actual button HTML
- **Fix applied**: Added `'button[aria-label="Start dictation" i]'` as first selector in `config.py`
- **Result**: Did NOT fix the error. Button still not found.

### Finding 2 — `evaluate_handle` returning null from minimized window (2026-03-31)
- Hypothesis: `evaluate_handle` silently fails returning DOM element handles from minimized windows
- **Fix applied**: Added `page.query_selector(selector)` as the first attempt in `find_element`
- **Result**: Did NOT fix the error. Button still not found.

### Finding 3 — `get_by_role` added (2026-03-31)
- Added `page.get_by_role("button", name=kw)` as the very first attempt in `find_element`
- This API matches by accessible name (aria-label OR innerText), more robust than CSS selectors
- **Result**: Did NOT fix the error. Button still not found.

### Finding 4 — Timing issue confirmed (2026-03-31) ← CURRENT HYPOTHESIS
- Improved debug dump to show `aria-label="..."` vs `text="..."` explicitly
- Log at 14:06:21 confirms button IS in DOM with correct `aria-label="Start dictation"`
- BUT: `find_element` ran at 14:06:19 and failed — 2 seconds before the dump
- Button appears to render AFTER `find_element` exhausts all attempts (each with ≤500ms timeout)
- The button is in the DOM by the time the debug dump runs, but wasn't there when we tried
- **Current fix being tested**: Increase `wait_for_selector` timeout from 500ms → 3000ms

## Files Modified
- `chatgpt_voice/config.py` — added `"Start dictation"` selector
- `chatgpt_voice/daemon.py` — `find_element()`: added `get_by_role`, `query_selector`, improved debug dump
- `chatgpt_voice/daemon.py` — login check: added `aria-label*="dictation"` guard

## State of `find_element` (current)
Order of attempts:
1. `get_by_role("button", name=kw)` for each keyword (timeout=500ms)
2. `page.query_selector(selector)` for each CSS selector (immediate)
3. `evaluate_handle` JS scan (immediate)
4. `wait_for_selector(selector, state="attached", timeout=500)` for each CSS selector

### Finding 5 — Root cause found: user config.json overriding defaults (2026-03-31) ✅ FIXED
- `C:\Users\kopro\AppData\Local\chatgpt-voice\config.json` contained hardcoded selectors
- This user config overrides `DEFAULT_CONFIG` in `config.py`, so all changes to `config.py` were ignored
- The file had only `"Dictate button"` and `"Dictate*"` selectors — neither matches `"Start dictation"`
- **Fix**: Added `"button[aria-label=\"Start dictation\" i]"` as first entry in `config.json`

## Resolution
- **Primary fix**: Add `"Start dictation"` to `mic_button` selectors in user `config.json`
- **Secondary improvement**: `start_recording` now uses a JS `evaluate()` poll loop (15s) as the
  primary click mechanism, which is more robust than Playwright element handle APIs in minimized windows
- **Note**: Any machine with a local `config.json` override needs the selector added manually

## Files Modified (committed)
- `chatgpt_voice/config.py` — added `"Start dictation"` as first default selector
- `chatgpt_voice/daemon.py` — JS poll loop as primary click, improved debug dump, updated login check
