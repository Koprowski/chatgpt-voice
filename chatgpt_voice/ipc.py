"""IPC layer — Unix socket (Linux/macOS) or TCP localhost (Windows)."""

import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path

from . import platform_utils

log = logging.getLogger("chatgpt-voice")

# ---------------------------------------------------------------------------
# Addressing
# ---------------------------------------------------------------------------

_TCP_PORT = 52384

if platform_utils.PLATFORM == "windows":
    _USE_TCP = True
else:
    _USE_TCP = False

_SOCKET_PATH = Path("/tmp/chatgpt-voice.sock")


def _pid_file() -> Path:
    if platform_utils.PLATFORM == "windows":
        from .config import config_dir
        return config_dir() / "daemon.pid"
    return Path("/tmp/chatgpt-voice.pid")


# ---------------------------------------------------------------------------
# Server (used by daemon)
# ---------------------------------------------------------------------------

async def start_server(client_handler) -> asyncio.AbstractServer:
    """Start the IPC server.  Returns the asyncio server object."""
    if _USE_TCP:
        server = await asyncio.start_server(
            client_handler, host="127.0.0.1", port=_TCP_PORT,
        )
        log.info("IPC listening on 127.0.0.1:%d", _TCP_PORT)
    else:
        # Clean up stale socket
        _SOCKET_PATH.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(client_handler, path=str(_SOCKET_PATH))
        os.chmod(str(_SOCKET_PATH), 0o600)
        log.info("IPC listening on %s", _SOCKET_PATH)
    return server


def write_pid() -> None:
    pf = _pid_file()
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(os.getpid()))


def cleanup() -> None:
    """Remove PID file and socket."""
    _pid_file().unlink(missing_ok=True)
    if not _USE_TCP:
        _SOCKET_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Client helpers (used by toggle / CLI)
# ---------------------------------------------------------------------------

def send_command(cmd: str, timeout: float = 15) -> str | None:
    """Send a command string to a running daemon and return the response."""
    try:
        if _USE_TCP:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(("127.0.0.1", _TCP_PORT))
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(str(_SOCKET_PATH))
        sock.send(cmd.encode())
        resp = sock.recv(4096).decode().strip()
        return resp
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return None
    finally:
        sock.close()


def is_daemon_running() -> bool:
    pf = _pid_file()
    if not pf.exists():
        return False
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        pf.unlink(missing_ok=True)
        return False

    if platform_utils.PLATFORM == "windows":
        # os.kill(pid, 0) works differently on Windows
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        pf.unlink(missing_ok=True)
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            pf.unlink(missing_ok=True)
            return False
