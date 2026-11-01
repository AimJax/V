import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from v.desktop.audio_devices import AudioDeviceOption
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
                "stt_device": "cpu",
                "stt_threads": 4,
                "whisper_server_path": "apps/whisper.cpp/build/bin/Release/whisper-server.exe",
                "whisper_cuda_server_path": "apps/whisper.cpp/build-cuda/bin/whisper-server.exe",
                "whisper_model_path": "models/whisper/ggml-small.bin",
                "silero_vad_model_path": "models/whisper/ggml-silero-v6.2.0.bin",
                "vad_threshold": 0.5,
                "vad_min_speech_duration_ms": 250,
                "vad_silence_duration_ms": 700,
                "max_utterance_seconds": 30,
                "kokoro_model_path": "models/kokoro/kokoro-v1.0.onnx",
                "kokoro_voices_path": "models/kokoro/voices-v1.0.bin",
                "kokoro_voice": "af_heart",
                "tts_speed": 1.0,
                "speak_replies": False,
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
        self.assertEqual(self.dialog.stt_device.currentData(), "cpu")
        self.assertEqual(
            self.dialog.whisper_cuda_server_path.text(),
            "apps/whisper.cpp/build-cuda/bin/whisper-server.exe",
        )
        self.assertEqual(
            self.dialog.kokoro_model_path.text(),
            "models/kokoro/kokoro-v1.0.onnx",
        )
        self.assertEqual(
            self.dialog.kokoro_voices_path.text(),
            "models/kokoro/voices-v1.0.bin",
        )

    def test_voice_activation_and_speech_output_are_explicit_opt_ins(self):
        self.assertFalse(self.dialog.voice_enabled.isChecked())
        self.assertFalse(self.dialog.speak_replies.isChecked())
        self.assertFalse(self.dialog.speak_replies.isEnabled())

        self.dialog.stt_device.setCurrentIndex(
            self.dialog.stt_device.findData("cuda")
        )
        self.dialog.voice_enabled.setChecked(True)
        self.assertTrue(self.dialog.speak_replies.isEnabled())
        self.dialog.speak_replies.setChecked(True)

        values = self.dialog._settings_values()
        self.assertTrue(values["voice_enabled"])
        self.assertEqual(values["voice_stt_device"], "cuda")
        self.assertEqual(
            values["voice_whisper_cuda_server_path"],
            "apps/whisper.cpp/build-cuda/bin/whisper-server.exe",
        )
        self.assertTrue(values["voice_speak_replies"])

        self.dialog.voice_enabled.setChecked(False)
        self.assertFalse(self.dialog.speak_replies.isChecked())
        self.assertFalse(self.dialog.speak_replies.isEnabled())

    def test_window_has_native_controls_and_fits_available_screen(self):
        flags = self.dialog.windowFlags()
        for flag in (
            Qt.WindowType.WindowTitleHint,
            Qt.WindowType.WindowSystemMenuHint,
            Qt.WindowType.WindowCloseButtonHint,
            Qt.WindowType.WindowMinimizeButtonHint,
            Qt.WindowType.WindowMaximizeButtonHint,
        ):
            self.assertTrue(flags & flag)

        self.assertTrue(self.dialog.isSizeGripEnabled())
        self.dialog.show()
        self.application.processEvents()

        screen = self.dialog.screen()
        if screen is not None:
            available = screen.availableGeometry()
            frame = self.dialog.frameGeometry()
            self.assertLessEqual(frame.width(), available.width())
            self.assertLessEqual(frame.height(), available.height())
            self.assertGreaterEqual(frame.left(), available.left())
            self.assertGreaterEqual(frame.top(), available.top())
            self.assertLessEqual(frame.right(), available.right())
            self.assertLessEqual(frame.bottom(), available.bottom())

    def test_settings_pages_are_scrollable_and_footer_remains_available(self):
        self.assertTrue(self.dialog.isSizeGripEnabled())
        self.assertLessEqual(self.dialog.minimumWidth(), 560)
        self.assertLessEqual(self.dialog.minimumHeight(), 420)

        self.assertEqual(
            [self.dialog.tabs.tabText(index) for index in range(self.dialog.tabs.count())],
            ["General", "Personality", "Memory", "Voice", "Privacy"],
        )
        for index in range(self.dialog.tabs.count()):
            page = self.dialog.tabs.widget(index)
            self.assertIsInstance(page, QScrollArea)
            self.assertTrue(page.widgetResizable())

        # The action buttons belong to the dialog footer, not an individual
        # tab page, so scrolling a long tab cannot move them out of view.
        self.assertIsNotNone(self.dialog.save_button.parentWidget())
        self.assertIsNotNone(self.dialog.close_button.parentWidget())

    def test_refreshing_audio_devices_does_not_create_unsaved_changes(self):
        with patch(
            "v.desktop.settings_dialog.list_audio_devices",
            side_effect=[
                [
                    AudioDeviceOption(
                        device_id="0011",
                        description="Test microphone",
                        is_default=True,
                    )
                ],
                [
                    AudioDeviceOption(
                        device_id="0022",
                        description="Test speaker",
                        is_default=True,
                    )
                ],
            ],
        ):
            self.dialog.refresh_audio_button.click()

        self.assertFalse(self.dialog._dirty)
        self.assertFalse(self.dialog.save_button.isEnabled())
        self.assertEqual(self.dialog.input_device.currentData(), "")
        self.assertEqual(self.dialog.output_device.currentData(), "")
        self.assertIn("Detected 1 microphone", self.dialog.audio_device_note.text())

        self.dialog.input_device.setCurrentIndex(1)
        self.assertTrue(self.dialog._dirty)
        self.assertTrue(self.dialog.save_button.isEnabled())

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
