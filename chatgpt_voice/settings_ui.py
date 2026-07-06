"""Tkinter control panel for provider and diagnostic settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__
from . import ipc
from .config import config_dir, config_file, load_config, log_file, save_config
from .shortcuts import install_windows_shortcuts, settings_icon_path


def _creationflags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _python_path() -> str:
    return sys.executable


def _workdir() -> Path:
    return Path(__file__).resolve().parents[1]


def _pid_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SettingsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = load_config()
        self.provider_var = tk.StringVar(value=self.config.get("provider", "chatgpt"))
        self.diagnostics_var = tk.BooleanVar(
            value=bool(self.config.get("diagnostics", {}).get("enabled", False))
        )
        self.status_var = tk.StringVar(value="Ready")
        self.status_text: tk.Text | None = None
        self.last_connection: dict | None = None
        self.tray_icon = None
        self.tray_thread: threading.Thread | None = None
        self._exiting = False
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.refresh_status()

    def _build(self) -> None:
        self.root.title("ChatGPT Voice Settings")
        if sys.platform == "win32":
            try:
                self.root.iconbitmap(str(settings_icon_path()))
            except tk.TclError:
                pass
        self.root.geometry("560x520")
        self.root.minsize(520, 480)

        style = ttk.Style(self.root)
        style.configure("Provider.Toolbutton", padding=(16, 6))

        frame = ttk.Frame(self.root, padding=(16, 12))
        frame.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(frame)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Settings", font=("Segoe UI", 15, "bold")).pack(side=tk.LEFT)
        header_actions = ttk.Frame(header)
        header_actions.pack(side=tk.RIGHT)
        ttk.Button(header_actions, text="Refresh", command=self.refresh_status).pack(anchor=tk.E)
        ttk.Label(
            header_actions,
            text=f"v{__version__}",
            foreground="#666666",
            font=("Segoe UI", 8),
        ).pack(anchor=tk.E, pady=(2, 0))

        provider_box = ttk.LabelFrame(frame, text="Provider", padding=(10, 8))
        provider_box.pack(fill=tk.X, pady=(10, 6))
        provider_row = ttk.Frame(provider_box)
        provider_row.pack(anchor=tk.W)
        for provider_id, provider in self.config.get("providers", {}).items():
            ttk.Radiobutton(
                provider_row,
                text=provider.get("name", provider_id),
                value=provider_id,
                variable=self.provider_var,
                command=self.save_settings,
                style="Provider.Toolbutton",
            ).pack(side=tk.LEFT, padx=(0, 8))

        diagnostics_box = ttk.LabelFrame(frame, text="Diagnostics", padding=(10, 8))
        diagnostics_box.pack(fill=tk.X, pady=6)
        ttk.Checkbutton(
            diagnostics_box,
            text="Enable diagnostic logs",
            variable=self.diagnostics_var,
            command=self.save_settings,
        ).pack(anchor=tk.W)
        ttk.Label(
            diagnostics_box,
            text=f"Config: {config_file()}",
            foreground="#555555",
        ).pack(anchor=tk.W, pady=(4, 0))

        daemon_box = ttk.LabelFrame(frame, text="Daemon", padding=(10, 8))
        daemon_box.pack(fill=tk.X, pady=6)
        buttons = ttk.Frame(daemon_box)
        buttons.pack(fill=tk.X)
        for label, command in [
            ("Start service", self.start_daemon),
            ("Stop service", self.stop_daemon),
            ("Restart service", self.restart_daemon),
            ("Test provider", self.test_connection),
        ]:
            ttk.Button(buttons, text=label, command=command).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(
            daemon_box,
            text=(
                "Service controls the global hotkey and provider browser. "
                "Restart clears stuck recording or recovery state. Test provider checks login, composer, and mic controls."
            ),
            foreground="#555555",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(6, 0))

        utilities = ttk.Frame(frame)
        utilities.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(utilities, text="Open log", command=self.open_log).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(utilities, text="Login browser", command=self.open_login_browser).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(utilities, text="Install shortcuts", command=self.install_shortcuts).pack(side=tk.LEFT)

        status = ttk.LabelFrame(frame, text="Status", padding=(10, 8))
        status.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        ttk.Label(status, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        text_frame = ttk.Frame(status)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.status_text = tk.Text(
            text_frame,
            height=7,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 9),
            relief=tk.FLAT,
            borderwidth=0,
        )
        y_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.status_text.yview)
        x_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.status_text.xview)
        self.status_text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.status_text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

    def _tray_image(self):
        try:
            from PIL import Image

            return Image.open(settings_icon_path())
        except Exception:
            return None

    def _ensure_tray_icon(self) -> bool:
        if self.tray_icon is not None:
            return True
        try:
            import pystray
        except ImportError:
            return False

        image = self._tray_image()
        if image is None:
            return False

        def call_on_ui(fn):
            return lambda _icon, _item: self.root.after(0, fn)

        menu = pystray.Menu(
            pystray.MenuItem("Show Settings", call_on_ui(self.show_window), default=True),
            pystray.MenuItem("Refresh Status", call_on_ui(self.refresh_status)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Service", call_on_ui(self.start_daemon)),
            pystray.MenuItem("Restart Service", call_on_ui(self.restart_daemon)),
            pystray.MenuItem("Stop Service", call_on_ui(self.stop_daemon)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit Settings", call_on_ui(self.exit_settings)),
        )
        self.tray_icon = pystray.Icon(
            "chatgpt-voice-settings",
            image,
            "ChatGPT Voice",
            menu,
        )
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()
        return True

    def hide_to_tray(self) -> None:
        if self._exiting:
            return
        if self._ensure_tray_icon():
            self.root.withdraw()
            return
        self.root.iconify()
        self._set_status(
            "Tray unavailable",
            "Install pystray and Pillow to minimize Settings to the notification area.",
        )

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        self.refresh_status()

    def exit_settings(self) -> None:
        self._exiting = True
        icon = self.tray_icon
        self.tray_icon = None
        if icon is not None:
            icon.stop()
        self.root.destroy()

    def _run_background(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _after_ui(self, fn) -> None:
        if self._exiting:
            return
        try:
            self.root.after(0, fn)
        except (RuntimeError, tk.TclError):
            pass

    def _set_status(self, status: str, detail: str = "") -> None:
        self._after_ui(lambda: self.status_var.set(status))
        self._after_ui(lambda: self._set_status_detail(detail))

    def _set_status_detail(self, detail: str) -> None:
        if self._exiting:
            return
        if self.status_text is None:
            return
        self.status_text.configure(state=tk.NORMAL)
        self.status_text.delete("1.0", tk.END)
        self.status_text.insert("1.0", detail)
        self.status_text.configure(state=tk.DISABLED)

    def _send(self, command: str, timeout: float = 15) -> dict | None:
        response = ipc.send_command(command, timeout=timeout)
        if not response:
            return None
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"status": response}

    def _provider_name(self) -> str:
        provider_id = self.provider_var.get()
        provider = self.config.get("providers", {}).get(provider_id, {})
        return provider.get("name", provider_id)

    def _visualizer_status(self) -> str:
        pid_file = config_dir() / "visualizer.pid"
        try:
            pid = int(pid_file.read_text().strip())
        except (FileNotFoundError, OSError, ValueError):
            return "not detected"
        return "running" if _pid_running(pid) else "not detected"

    def _compact_for_display(self, result: dict | None) -> dict:
        if not result:
            return {}
        compact = dict(result)
        labels = compact.get("button_labels")
        if isinstance(labels, list) and len(labels) > 20:
            compact["button_labels"] = labels[:20] + [f"... {len(labels) - 20} more omitted"]
        return compact

    def _health_summary(self, status_result: dict | None = None, connection: dict | None = None) -> tuple[str, str]:
        provider = (status_result or connection or {}).get("provider_name") or self._provider_name()
        daemon_running = ipc.is_daemon_running()
        overlay = self._visualizer_status()

        if not daemon_running:
            return (
                "Not running",
                "\n".join([
                    "Overall: Not running",
                    f"Provider: {provider} selected",
                    "Hotkey: inactive",
                    f"Overlay: {overlay}",
                    "",
                    "Use Start service to turn on Ctrl+Shift+Period dictation.",
                ]),
            )

        state = (status_result or {}).get("status", "unknown")
        connection_state = "not tested"
        if connection:
            if connection.get("login_required"):
                connection_state = "login required"
            elif connection.get("composer_found") and (connection.get("mic_found") or connection.get("stop_found")):
                connection_state = "connected"
            else:
                connection_state = "provider controls not found"

        if state == "idle":
            headline = "Operational" if connection_state in ("connected", "not tested") else "Needs attention"
            next_action = "Press Ctrl+Shift+Period to start recording."
        elif state == "recording":
            headline = "Recording"
            next_action = "Press Ctrl+Shift+Period again to stop and paste the transcript."
        elif state == "processing":
            headline = "Processing transcript"
            next_action = "Wait for the provider to finish transcription."
        elif state == "recovering":
            headline = "Waiting for late text"
            next_action = "Restart service if Gemini is visibly idle and no transcript is expected."
        else:
            headline = "Needs attention"
            next_action = "Use Test provider, then Restart service if the provider page looks wrong."

        detail = "\n".join([
            f"Overall: {headline}",
            f"Daemon: running ({state})",
            f"Provider: {provider} ({connection_state})",
            f"Overlay: {overlay}",
            "Hotkey: active",
            f"Next: {next_action}",
        ])
        return headline, detail

    def _status_detail(self, health: str, result: dict | None = None) -> str:
        raw = json.dumps(self._compact_for_display(result), indent=2)
        return f"{health}\n\nDetails:\n{raw}"

    def save_settings(self) -> None:
        config = load_config()
        config["provider"] = self.provider_var.get()
        config.setdefault("diagnostics", {})["enabled"] = bool(self.diagnostics_var.get())
        saved = save_config(config)
        self.config = saved
        self.last_connection = None
        provider = saved["providers"][saved["provider"]].get("name", saved["provider"])
        self._set_status("Settings saved", f"Provider: {provider}")

        def reload_running_daemon() -> None:
            result = self._send("reload_config", timeout=20)
            if result:
                self._set_status(
                    "Daemon reloaded",
                    json.dumps(result, indent=2),
                )

        if ipc.is_daemon_running():
            self._run_background(reload_running_daemon)

    def refresh_status(self) -> None:
        def work() -> None:
            if not ipc.is_daemon_running():
                headline, health = self._health_summary()
                self._set_status(headline, health)
                return
            result = self._send("status")
            headline, health = self._health_summary(result, self.last_connection)
            self._set_status(headline, self._status_detail(health, result))

        self._run_background(work)

    def start_daemon(self) -> None:
        def work() -> None:
            if ipc.is_daemon_running():
                self.refresh_status()
                return
            subprocess.Popen(
                [_python_path(), "-m", "chatgpt_voice", "start"],
                cwd=_workdir(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
            )
            time.sleep(2)
            self.refresh_status()

        self._run_background(work)

    def stop_daemon(self) -> None:
        def work() -> None:
            subprocess.run(
                [_python_path(), "-m", "chatgpt_voice", "stop"],
                cwd=_workdir(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
                timeout=20,
                check=False,
            )
            time.sleep(0.5)
            self.refresh_status()

        self._run_background(work)

    def restart_daemon(self) -> None:
        def work() -> None:
            subprocess.run(
                [_python_path(), "-m", "chatgpt_voice", "stop"],
                cwd=_workdir(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
                timeout=20,
                check=False,
            )
            time.sleep(1)
            subprocess.Popen(
                [_python_path(), "-m", "chatgpt_voice", "start"],
                cwd=_workdir(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
            )
            time.sleep(2)
            self.refresh_status()

        self._run_background(work)

    def test_connection(self) -> None:
        def work() -> None:
            if not ipc.is_daemon_running():
                headline, health = self._health_summary()
                self._set_status(headline, health)
                return
            result = self._send("test_connection", timeout=30)
            self.last_connection = result
            status_result = self._send("status")
            headline, health = self._health_summary(status_result, result)
            self._set_status(headline, self._status_detail(health, result))

        self._run_background(work)

    def open_log(self) -> None:
        path = log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def open_login_browser(self) -> None:
        def work() -> None:
            if ipc.is_daemon_running():
                self._set_status(
                    "Daemon is running",
                    "Stop the daemon before opening a provider login browser.",
                )
                return
            subprocess.Popen(
                [_python_path(), "-m", "chatgpt_voice", "login"],
                cwd=_workdir(),
            )
            self._set_status(
                "Login browser opening",
                "Close the browser or stop the command when login is complete.",
            )

        self._run_background(work)

    def install_shortcuts(self) -> None:
        def work() -> None:
            try:
                paths = install_windows_shortcuts()
            except Exception as exc:
                self._set_status("Shortcut install failed", str(exc))
                return
            self._set_status(
                "Shortcuts installed",
                "\n".join(str(path) for path in paths),
            )
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "ChatGPT Voice",
                    "Desktop and Start Menu shortcuts installed.",
                ),
            )

        self._run_background(work)


def run_settings_ui() -> None:
    root = tk.Tk()
    app = SettingsApp(root)
    try:
        root.mainloop()
    finally:
        if app.tray_icon is not None:
            app.tray_icon.stop()
