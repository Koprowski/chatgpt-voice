"""CLI entry point: python -m chatgpt_voice {start|login|stop|toggle|status|visualizer}"""

import asyncio
import logging
import subprocess
import sys

from .config import load_config
from . import ipc
from .platform_utils import send_notification


def _start_visualizer_background():
    """Launch the recording wave visualizer as a detached subprocess (no extra window)."""
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # 0x08000000
        subprocess.Popen(
            [sys.executable, "-m", "chatgpt_voice", "visualizer"],
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(sys.platform != "win32"),
        )
    except Exception:
        pass  # non-fatal; daemon still runs without visualizer


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )


def main(argv: list[str] | None = None):
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python -m chatgpt_voice {start|login|stop|toggle|status|visualizer}")
        sys.exit(1)

    cmd = args[0]

    if cmd == "visualizer":
        from .visualizer import run_visualizer
        run_visualizer()
        return

    _setup_logging()
    config = load_config()

    if cmd == "start":
        if ipc.is_daemon_running():
            print("Daemon already running.")
            sys.exit(0)
        _start_visualizer_background()
        from .daemon import VoiceDaemon
        daemon = VoiceDaemon(config, visible=False)
        asyncio.run(daemon.run())

    elif cmd == "login":
        if ipc.is_daemon_running():
            print("Stop the daemon first: python -m chatgpt_voice stop")
            sys.exit(1)
        print("Opening browser for login. Log in to ChatGPT, then close the browser.")
        from .daemon import VoiceDaemon
        daemon = VoiceDaemon(config, visible=True)
        asyncio.run(daemon.run())

    elif cmd == "stop":
        if ipc.is_daemon_running():
            resp = ipc.send_command("quit")
            print(resp or "Sent quit signal.")
        else:
            print("Daemon not running.")

    elif cmd == "status":
        if ipc.is_daemon_running():
            resp = ipc.send_command("status")
            print(resp or "No response.")
        else:
            print("Daemon not running.")

    elif cmd == "toggle":
        if not ipc.is_daemon_running():
            print("Daemon not running. Start it first: python -m chatgpt_voice start")
            sys.exit(1)
        resp = ipc.send_command("toggle")
        print(resp or "No response.")

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: start, login, stop, toggle, status, visualizer")
        sys.exit(1)


if __name__ == "__main__":
    main()
