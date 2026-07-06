import unittest

from chatgpt_voice.config import merge_config
from chatgpt_voice.daemon import VoiceDaemon


class VoiceDaemonProviderTests(unittest.TestCase):
    def test_daemon_uses_selected_provider(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        self.assertEqual(daemon.provider_id, "gemini")
        self.assertEqual(daemon._provider_name(), "Gemini")
        self.assertEqual(daemon._provider_url(), "https://gemini.google.com/")

    def test_provider_keywords_include_selector_aria_labels(self):
        daemon = VoiceDaemon(merge_config({
            "provider": "gemini",
            "providers": {
                "gemini": {
                    "selectors": {
                        "mic_button": ['button[aria-label="Use microphone" i]'],
                    },
                },
            },
        }))

        keywords = daemon._provider_keywords("mic_button")

        self.assertIn("use microphone", keywords)
        self.assertIn("microphone", keywords)

    def test_apply_config_updates_provider_and_diagnostics(self):
        daemon = VoiceDaemon(merge_config({}))

        daemon._apply_config(merge_config({
            "provider": "gemini",
            "diagnostics": {"enabled": True},
        }))

        self.assertEqual(daemon.provider_id, "gemini")
        self.assertTrue(daemon.diagnostics_enabled)

    def test_idle_without_text_detection(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        self.assertTrue(daemon._is_idle_without_text({
            "observed": "idle",
            "textLength": 0,
            "hasProcessing": False,
        }))
        self.assertFalse(daemon._is_idle_without_text({
            "observed": "idle",
            "textLength": 12,
            "hasProcessing": False,
        }))
        self.assertFalse(daemon._is_idle_without_text({
            "observed": "processing",
            "textLength": 0,
            "hasProcessing": True,
        }))

    def test_ignored_button_prefixes_cover_sidebar_history_controls(self):
        daemon = VoiceDaemon(merge_config({"provider": "chatgpt"}))

        prefixes = daemon._ignored_button_label_prefixes()

        self.assertIn("open conversation options for", prefixes)
        self.assertIn("pin ", prefixes)
        self.assertIn("more options for", prefixes)

    def test_transcript_not_ready_while_still_changing_or_busy(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        self.assertFalse(daemon._transcript_ready_for_capture(
            text="partial transcript",
            pre_record_text="",
            observed_state="recording",
            elapsed=0.4,
            last_changed_at=0.4,
            min_wait=1.2,
            stable_wait=1.6,
            busy_grace=3.0,
        ))
        self.assertFalse(daemon._transcript_ready_for_capture(
            text="partial transcript",
            pre_record_text="",
            observed_state="recording",
            elapsed=2.5,
            last_changed_at=0.4,
            min_wait=1.2,
            stable_wait=1.6,
            busy_grace=3.0,
        ))

    def test_transcript_ready_after_stable_wait_and_busy_grace(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        self.assertTrue(daemon._transcript_ready_for_capture(
            text="complete transcript",
            pre_record_text="",
            observed_state="recording",
            elapsed=3.2,
            last_changed_at=1.4,
            min_wait=1.2,
            stable_wait=1.6,
            busy_grace=3.0,
        ))

    def test_post_stop_timing_uses_global_defaults_without_provider_override(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        self.assertEqual(daemon._post_stop_delay_ms("min_wait_ms", "post_stop_min_wait_ms"), 1200)
        self.assertEqual(daemon._post_stop_delay_ms("text_stable_ms", "post_stop_text_stable_ms"), 1600)
        self.assertEqual(daemon._post_stop_delay_ms("busy_grace_ms", "post_stop_busy_grace_ms"), 3000)

    def test_transcript_candidate_keeps_pre_stop_trailing_text_regression(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        chosen = daemon._choose_transcript_candidate(
            current_text="This is the transcript before the final",
            best_text="This is the transcript before the final word",
            pre_record_text="",
        )

        self.assertEqual(chosen, "This is the transcript before the final word")

    def test_transcript_candidate_accepts_later_longer_text(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        chosen = daemon._choose_transcript_candidate(
            current_text="This is the transcript before the final word appears",
            best_text="This is the transcript before the final word",
            pre_record_text="",
        )

        self.assertEqual(chosen, "This is the transcript before the final word appears")

    def test_quick_status_uses_internal_flags_without_page_inspection(self):
        daemon = VoiceDaemon(merge_config({"provider": "gemini"}))

        self.assertEqual(daemon._quick_status_state(), "idle")
        daemon.recording = True
        self.assertEqual(daemon._quick_status_state(), "recording")
        daemon.recording = False
        daemon.processing = True
        self.assertEqual(daemon._quick_status_state(), "processing")
        daemon.processing = False
        daemon.recovering = True
        self.assertEqual(daemon._quick_status_state(), "recovering")
        self.assertTrue(daemon._transcript_ready_for_capture(
            text="complete transcript",
            pre_record_text="",
            observed_state="idle",
            elapsed=2.0,
            last_changed_at=0.3,
            min_wait=1.2,
            stable_wait=1.6,
            busy_grace=3.0,
        ))


if __name__ == "__main__":
    unittest.main()
