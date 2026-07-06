import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chatgpt_voice import config
from chatgpt_voice.shortcuts import settings_icon_path


class ShortcutTests(unittest.TestCase):
    def test_settings_icon_path_generates_ico(self):
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td)
            with patch.object(config, "_config_dir", return_value=config_dir):
                path = settings_icon_path()

                data = path.read_bytes()

        self.assertEqual(path.name, "settings.ico")
        self.assertGreater(len(data), 100)
        self.assertEqual(data[:4], b"\x00\x00\x01\x00")


if __name__ == "__main__":
    unittest.main()
