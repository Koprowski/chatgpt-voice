import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chatgpt_voice import config


class ConfigTests(unittest.TestCase):
    def test_default_provider_is_chatgpt(self):
        merged = config.merge_config({})

        self.assertEqual(merged["provider"], "chatgpt")
        self.assertIn("chatgpt", merged["providers"])
        self.assertIn("gemini", merged["providers"])

    def test_legacy_chatgpt_selectors_merge_into_chatgpt_provider(self):
        merged = config.merge_config({
            "selectors": {
                "mic_button": ['button[aria-label="Custom Dictate" i]'],
            },
        })

        selectors = merged["providers"]["chatgpt"]["selectors"]["mic_button"]
        self.assertEqual(selectors[0], 'button[aria-label="Custom Dictate" i]')
        self.assertIn('button[aria-label="Start dictation" i]', selectors)

    def test_gemini_provider_can_be_selected(self):
        merged = config.merge_config({"provider": "gemini"})
        provider = config.get_provider_config(merged)

        self.assertEqual(provider["id"], "gemini")
        self.assertEqual(provider["url"], "https://gemini.google.com/")
        self.assertIn("mic_button", provider["selectors"])

    def test_save_config_normalizes_file(self):
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td)
            with patch.object(config, "_config_dir", return_value=config_dir):
                saved = config.save_config({
                    "provider": "gemini",
                    "diagnostics": {"enabled": True},
                })

                raw = json.loads((config_dir / "config.json").read_text())

        self.assertEqual(saved["provider"], "gemini")
        self.assertTrue(raw["diagnostics"]["enabled"])
        self.assertIn("providers", raw)


if __name__ == "__main__":
    unittest.main()
