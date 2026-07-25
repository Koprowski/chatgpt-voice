import unittest
from unittest.mock import MagicMock, patch

from chatgpt_voice import ipc


class IpcTests(unittest.TestCase):
    def test_tcp_daemon_responds_requires_status_json(self):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.return_value = b'{"status": "idle"}\n'

        with patch.object(ipc.socket, "create_connection", return_value=sock):
            self.assertTrue(ipc._tcp_daemon_responds())

    def test_tcp_daemon_responds_rejects_empty_or_invalid_response(self):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.return_value = b""

        with patch.object(ipc.socket, "create_connection", return_value=sock):
            self.assertFalse(ipc._tcp_daemon_responds())

        sock.recv.return_value = b"not json"
        with patch.object(ipc.socket, "create_connection", return_value=sock):
            self.assertFalse(ipc._tcp_daemon_responds())
