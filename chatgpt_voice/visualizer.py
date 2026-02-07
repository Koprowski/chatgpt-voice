"""Recording indicator — scrolling waveform like ChatGPT voice UI."""

import collections
import json
import os
import queue
import sys
import time

from . import ipc
from .config import config_dir

try:
    import sounddevice as sd
    import tkinter as tk
    _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False

_SAMPLE_RATE = 16000
_BLOCKSIZE = 512          # smaller blocks = more waveform resolution
_NUM_BARS = 80            # number of vertical lines in the waveform
_BAR_W = 3                # width of each vertical line (px)
_BAR_GAP = 1              # gap between lines (px)
_BAR_COLOR = "#d1d1d1"    # light gray (ChatGPT style)
_BG_COLOR = "#1a1a1a"     # dark background
_WIN_H = 80               # window height
_POLL_MS_RECORDING = 50   # fast updates for smooth scrolling
_POLL_MS_IDLE = 600
_VISUALIZER_LOCK = "visualizer.lock"

# Compute window width from bar count
_WIN_W = _NUM_BARS * (_BAR_W + _BAR_GAP) + _BAR_GAP


def _get_status() -> str | None:
    if not ipc.is_daemon_running():
        return None
    try:
        resp = ipc.send_command("status", timeout=2)
        if resp:
            data = json.loads(resp.strip())
            return data.get("status")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def run_visualizer():
    """Run the recording indicator — scrolling centered waveform."""
    if not _HAS_DEPS:
        sys.stderr.write("visualizer requires: pip install sounddevice\n")
        return

    # Single instance: Windows named mutex (atomic, auto-releases on exit/crash)
    if sys.platform == "win32":
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, True,
                                                      "chatgpt_voice_visualizer_mutex")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            sys.exit(0)
    else:
        lock_file = config_dir() / _VISUALIZER_LOCK
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            import fcntl
            _lock_fh = open(lock_file, "w")
            fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_fh.write(str(os.getpid()))
            _lock_fh.flush()
        except (IOError, OSError):
            sys.exit(0)

    amp_queue: queue.Queue[float] = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        if status:
            return
        # Peak amplitude per block — gives more waveform variation than RMS
        peak = max(abs(float(x)) for x in indata[:, 0])
        try:
            amp_queue.put_nowait(peak)
        except queue.Full:
            pass

    stream = None
    root = None
    cv = None
    line_ids: list = []
    # Rolling buffer of amplitude values — fills from right, scrolls left
    waveform = collections.deque([0.0] * _NUM_BARS, maxlen=_NUM_BARS)

    while True:
        status = _get_status()
        if status == "recording":
            # Start mic stream
            if stream is None:
                try:
                    stream = sd.InputStream(
                        samplerate=_SAMPLE_RATE,
                        blocksize=_BLOCKSIZE,
                        channels=1,
                        dtype="float32",
                        callback=audio_callback,
                    )
                    stream.start()
                except Exception:
                    time.sleep(_POLL_MS_IDLE / 1000.0)
                    continue

            # Create window
            if root is None:
                root = tk.Tk()
                root.overrideredirect(True)
                root.attributes("-topmost", True)
                root.configure(bg=_BG_COLOR)
                root.resizable(False, False)
                try:
                    sw = root.winfo_screenwidth()
                    root.geometry(f"{_WIN_W}x{_WIN_H}+{(sw - _WIN_W) // 2}+16")
                except Exception:
                    root.geometry(f"{_WIN_W}x{_WIN_H}")

                cv = tk.Canvas(root, width=_WIN_W, height=_WIN_H,
                               bg=_BG_COLOR, highlightthickness=0, bd=0)
                cv.pack()

                # Draw center reference line (subtle)
                center_y = _WIN_H // 2
                cv.create_line(0, center_y, _WIN_W, center_y,
                               fill="#333333", width=1, dash=(2, 4))

                # Pre-create vertical line items (centered on middle)
                line_ids = []
                for i in range(_NUM_BARS):
                    x = _BAR_GAP + i * (_BAR_W + _BAR_GAP) + _BAR_W // 2
                    lid = cv.create_line(x, center_y, x, center_y,
                                         fill=_BAR_COLOR, width=_BAR_W,
                                         capstyle=tk.ROUND)
                    line_ids.append(lid)

                def close_win(_event=None):
                    try:
                        root.destroy()
                    except Exception:
                        pass

                root.bind("<Escape>", close_win)
                root.bind("<Button-3>", close_win)

                # Reset waveform buffer
                waveform.clear()
                waveform.extend([0.0] * _NUM_BARS)

            # --- Update loop while recording ---
            center_y = _WIN_H // 2
            max_half = (_WIN_H // 2) - 4  # max half-height (leave margin)

            while _get_status() == "recording" and root is not None:
                try:
                    root.update()
                except tk.TclError:
                    root = None
                    break

                # Drain amplitude queue into rolling buffer (scrolls left)
                new_vals = []
                try:
                    while True:
                        new_vals.append(amp_queue.get_nowait())
                except queue.Empty:
                    pass

                if new_vals:
                    for v in new_vals:
                        waveform.append(v)

                # Adaptive scaling: use recent peak for normalization
                peak = max(waveform) if waveform else 0.0
                scale = max(peak, 0.005)  # floor to avoid division by tiny values

                # Update each vertical line
                for i, (lid, amp) in enumerate(zip(line_ids, waveform)):
                    norm = min(1.0, amp / scale)
                    half_h = max(1, int(norm * max_half))
                    x = _BAR_GAP + i * (_BAR_W + _BAR_GAP) + _BAR_W // 2
                    cv.coords(lid, x, center_y - half_h, x, center_y + half_h)

                time.sleep(_POLL_MS_RECORDING / 1000.0)

            # Recording ended: tear down
            if root is not None:
                try:
                    root.destroy()
                except (tk.TclError, Exception):
                    pass
                root = None
            cv = None
            line_ids = []
            waveform.clear()
            waveform.extend([0.0] * _NUM_BARS)
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                stream = None
        else:
            if root is not None:
                try:
                    root.destroy()
                except (tk.TclError, Exception):
                    pass
                root = None
            cv = None
            line_ids = []
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                stream = None
            time.sleep(_POLL_MS_IDLE / 1000.0)


if __name__ == "__main__":
    run_visualizer()
