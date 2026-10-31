import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from v.desktop.service import DesktopSettingsSnapshot
from v.desktop.settings_dialog import SettingsDialog


class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = SettingsDialog()
        self.dialog.set_snapshot(self._snapshot())
        self.application.processEvents()

    def tearDown(self):
        self.dialog._dirty = False
        self.dialog._saving = False
        self.dialog.close()
        self.application.processEvents()

    @staticmethod
    def _snapshot():
        return DesktopSettingsSnapshot(
            model="gemma-chat",
            available_models=["gemma-chat", "nomic-embed"],
            temperature=0.7,
            max_tokens=512,
            history_messages=24,
            offline_mode=True,
            memory_enabled=True,
            automatic_extraction=True,
            retrieval_enabled=True,
            embedding_model="nomic-embed",
            minimum_confidence=0.90,
            idle_delay_seconds=20.0,
            max_jobs_per_idle_cycle=3,
            semantic_threshold=0.60,
            retrieval_limit=5,
            retrieval_max_characters=2400,
            personality="You are V. Be direct and honest.",
            personality_path="G:/V/config/personality.md",
            voice={
                "enabled": False,
                "wake_phrase": "Hey V",
                "input_device_id": "",
                "output_device_id": "",
                "sample_rate": 16000,
                "stt_language": "auto",
                "stt_threads": 4,
                "whisper_server_path": "apps/whisper.cpp/build/bin/Release/whisper-server.exe",
                "whisper_model_path": "models/whisper/ggml-base.bin",
                "silero_vad_model_path": "models/whisper/ggml-silero-v6.2.0.bin",
                "vad_threshold": 0.5,
                "vad_min_speech_duration_ms": 250,
                "vad_silence_duration_ms": 700,
                "max_utterance_seconds": 30,
                "kokoro_python_path": ".venv/Scripts/python.exe",
                "kokoro_model_path": "models/kokoro/kokoro-v1.0.onnx",
                "kokoro_voices_path": "models/kokoro/voices-v1.0.bin",
                "kokoro_voice": "af_heart",
                "tts_speed": 1.0,
            },
        )

    def test_snapshot_populates_settings_and_loaded_models(self):
        self.assertEqual(self.dialog.chat_model.currentData(), "gemma-chat")
        self.assertEqual(
            self.dialog.embedding_model.currentData(),
            "nomic-embed",
        )
        self.assertTrue(self.dialog.offline_mode.isChecked())
        self.assertEqual(self.dialog.max_tokens.value(), 512)
        self.assertEqual(
            self.dialog.personality_text.toPlainText(),
            "You are V. Be direct and honest.",
        )
        self.assertFalse(self.dialog._dirty)
        self.assertFalse(self.dialog.save_button.isEnabled())
        self.assertEqual(
            self.dialog.kokoro_model_path.text(),
            "models/kokoro/kokoro-v1.0.onnx",
        )
        self.assertEqual(
            self.dialog.kokoro_voices_path.text(),
            "models/kokoro/voices-v1.0.bin",
        )

    def test_edits_mark_settings_dirty(self):
        self.dialog.max_tokens.setValue(1024)
        self.assertTrue(self.dialog._dirty)
        self.assertEqual(self.dialog.status_label.text(), "Unsaved changes")
        self.assertTrue(self.dialog.save_button.isEnabled())

    def test_save_emits_all_configurable_values_and_personality(self):
        emitted = []
        self.dialog.save_requested.connect(
            lambda changes, personality: emitted.append((changes, personality))
        )
        self.dialog.temperature.setValue(0.55)
        self.dialog.max_tokens.setValue(1024)
        self.dialog.offline_mode.setChecked(False)
        self.dialog.personality_text.setPlainText(
            "You are V. Keep private processing local."
        )

        self.dialog._save()

        self.assertEqual(len(emitted), 1)
        changes, personality = emitted[0]
        self.assertEqual(changes["model"], "gemma-chat")
        self.assertEqual(changes["temperature"], 0.55)
        self.assertEqual(changes["max_tokens"], 1024)
        self.assertFalse(changes["offline_mode"])
        self.assertEqual(personality, "You are V. Keep private processing local.")
        self.assertTrue(self.dialog._saving)

    def test_memory_controls_follow_master_and_retrieval_toggles(self):
        self.dialog.memory_enabled.setChecked(False)
        self.assertFalse(self.dialog.automatic_extraction.isEnabled())
        self.assertFalse(self.dialog.retrieval_enabled.isEnabled())
        self.assertFalse(self.dialog.embedding_model.isEnabled())

        self.dialog.memory_enabled.setChecked(True)
        self.dialog.retrieval_enabled.setChecked(False)
        self.assertTrue(self.dialog.automatic_extraction.isEnabled())
        self.assertTrue(self.dialog.retrieval_enabled.isEnabled())
        self.assertFalse(self.dialog.embedding_model.isEnabled())

        self.dialog.retrieval_enabled.setChecked(True)
        self.assertTrue(self.dialog.embedding_model.isEnabled())

    def test_save_result_requires_restart_and_clears_dirty_state(self):
        self.dialog.max_tokens.setValue(1024)
        self.dialog.on_saved("Saved. Restart V to apply the changes.")
        self.assertFalse(self.dialog._dirty)
        self.assertFalse(self.dialog._saving)
        self.assertFalse(self.dialog.save_button.isEnabled())
        self.assertIn("Restart V", self.dialog.status_label.text())


if __name__ == "__main__":
    unittest.main()
