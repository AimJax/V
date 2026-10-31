import unittest

from pathlib import Path
from unittest.mock import patch

from v.desktop.service import DesktopService


class DesktopSettingsSnapshotServiceTests(unittest.TestCase):
    def test_settings_snapshot_reads_loaded_configuration(self):
        with patch(
            "v.desktop.service.project_root",
            return_value=Path("G:/V"),
        ):
            service = DesktopService()
            service.settings = {
                "llm": {
                    "model": "gemma-4-e4b-it",
                    "temperature": 0.7,
                    "max_tokens": 512,
                    "history_messages": 24,
                },
                "memory": {
                    "enabled": True,
                    "automatic_extraction": True,
                    "retrieval_enabled": True,
                    "embedding_model": "text-embedding-nomic-embed-text-v1.5",
                    "minimum_confidence": 0.9,
                    "idle_delay_seconds": 20,
                    "max_jobs_per_idle_cycle": 3,
                    "semantic_threshold": 0.6,
                    "retrieval_limit": 5,
                    "retrieval_max_characters": 2400,
                },
                "privacy": {"offline_mode": True},
                "paths": {"personality": "config/personality.md"},
            }
            service.available_models = [
                "gemma-4-e4b-it",
                "text-embedding-nomic-embed-text-v1.5",
            ]
            service.model = "gemma-4-e4b-it"
            service.personality = "You are V."

            snapshot = service.settings_snapshot()

        self.assertEqual(snapshot.model, "gemma-4-e4b-it")
        self.assertEqual(snapshot.available_models, [
            "gemma-4-e4b-it",
            "text-embedding-nomic-embed-text-v1.5",
        ])
        self.assertEqual(snapshot.temperature, 0.7)
        self.assertEqual(snapshot.max_tokens, 512)
        self.assertEqual(snapshot.history_messages, 24)
        self.assertTrue(snapshot.offline_mode)
        self.assertTrue(snapshot.memory_enabled)
        self.assertTrue(snapshot.retrieval_enabled)
        self.assertEqual(snapshot.personality, "You are V.")
        self.assertEqual(
            snapshot.personality_path,
            str(Path("G:/V/config/personality.md")),
        )


if __name__ == "__main__":
    unittest.main()
