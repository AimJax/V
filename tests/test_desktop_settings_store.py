import tempfile
import tomllib
import unittest

from pathlib import Path
from unittest.mock import patch

from v.desktop.settings_store import (
    save_local_desktop_settings,
    validate_desktop_settings,
)


def valid_changes():
    return {
        "model": "gemma-chat",
        "temperature": 0.65,
        "max_tokens": 768,
        "history_messages": 30,
        "offline_mode": True,
        "memory_enabled": True,
        "automatic_extraction": True,
        "retrieval_enabled": True,
        "embedding_model": "nomic-embed",
        "minimum_confidence": 0.92,
        "idle_delay_seconds": 25.0,
        "max_jobs_per_idle_cycle": 4,
        "semantic_threshold": 0.62,
        "retrieval_limit": 6,
        "retrieval_max_characters": 2600,
        "voice_enabled": False,
        "voice_wake_phrase": "Hey V",
        "voice_input_device_id": "",
        "voice_output_device_id": "",
        "voice_sample_rate": 16000,
        "voice_stt_language": "auto",
        "voice_stt_threads": 4,
        "voice_whisper_server_path": "apps/whisper.cpp/build/bin/Release/whisper-server.exe",
        "voice_whisper_model_path": "models/whisper/ggml-base.bin",
        "voice_silero_vad_model_path": "models/whisper/ggml-silero-v6.2.0.bin",
        "voice_vad_threshold": 0.50,
        "voice_vad_min_speech_duration_ms": 250,
        "voice_vad_silence_duration_ms": 700,
        "voice_max_utterance_seconds": 30,
        "voice_kokoro_python_path": ".venv/Scripts/python.exe",
        "voice_kokoro_voice": "af_heart",
        "voice_tts_speed": 1.0,
    }


class DesktopSettingsStoreTests(unittest.TestCase):
    def test_validates_settings_ranges_and_loaded_models(self):
        changes = valid_changes()
        normalized = validate_desktop_settings(
            changes,
            available_models=["gemma-chat", "nomic-embed"],
        )
        self.assertEqual(normalized["model"], "gemma-chat")
        self.assertEqual(normalized["max_tokens"], 768)

    def test_rejects_unloaded_chat_model(self):
        changes = valid_changes()
        changes["model"] = "not-loaded"

        with self.assertRaisesRegex(ValueError, "not loaded"):
            validate_desktop_settings(
                changes,
                available_models=["gemma-chat", "nomic-embed"],
            )

    def test_rejects_same_chat_and_embedding_model(self):
        changes = valid_changes()
        changes["embedding_model"] = changes["model"]

        with self.assertRaisesRegex(ValueError, "different"):
            validate_desktop_settings(
                changes,
                available_models=["gemma-chat", "nomic-embed"],
            )

    def test_rejects_boolean_temperature_and_out_of_range_history(self):
        changes = valid_changes()
        changes["temperature"] = True
        with self.assertRaisesRegex(ValueError, "numeric"):
            validate_desktop_settings(
                changes,
                available_models=["gemma-chat", "nomic-embed"],
            )

        changes = valid_changes()
        changes["history_messages"] = 1
        with self.assertRaisesRegex(ValueError, "between 2 and 200"):
            validate_desktop_settings(
                changes,
                available_models=["gemma-chat", "nomic-embed"],
            )

    def test_save_preserves_existing_local_settings_and_writes_utf8_without_bom(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            local_file = config_dir / "local.toml"
            local_file.write_text(
                '[privacy]\noffline_mode = true\n\n[custom]\nkeep = "preserve-me"\n',
                encoding="utf-8",
            )
            personality_file = config_dir / "personality.md"
            personality_file.write_text("Old personality", encoding="utf-8")

            settings = {
                "paths": {"personality": "config/personality.md"},
            }

            with patch(
                "v.desktop.settings_store.project_root",
                return_value=root,
            ):
                saved_local, saved_personality = save_local_desktop_settings(
                    settings,
                    valid_changes(),
                    "You are V. Be direct and transparent.",
                    available_models=["gemma-chat", "nomic-embed"],
                )

            raw = saved_local.read_bytes()
            parsed = tomllib.loads(raw.decode("utf-8"))
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(parsed["privacy"]["offline_mode"], True)
            self.assertEqual(parsed["custom"]["keep"], "preserve-me")
            self.assertEqual(parsed["llm"]["model"], "gemma-chat")
            self.assertEqual(parsed["llm"]["max_tokens"], 768)
            self.assertEqual(parsed["memory"]["embedding_model"], "nomic-embed")
            self.assertEqual(
                saved_personality.read_text(encoding="utf-8"),
                "You are V. Be direct and transparent.",
            )

    def test_rejects_personality_path_outside_project_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            outside = root.parent / "outside-personality.md"
            settings = {"paths": {"personality": str(outside)}}

            with patch(
                "v.desktop.settings_store.project_root",
                return_value=root,
            ):
                with self.assertRaisesRegex(ValueError, "outside"):
                    save_local_desktop_settings(
                        settings,
                        valid_changes(),
                        "A valid personality.",
                        available_models=["gemma-chat", "nomic-embed"],
                    )


if __name__ == "__main__":
    unittest.main()
