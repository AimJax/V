import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v.core.config import load_settings, project_root


class ConfigurationTests(unittest.TestCase):
    def test_project_root_is_existing_directory(self):
        self.assertTrue(project_root().is_dir())

    def test_v_home_overrides_project_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "default.toml").write_text(
                '[app]\nname = "V test"\n', encoding="utf-8"
            )
            with patch.dict(os.environ, {"V_HOME": str(root)}):
                self.assertEqual(project_root(), root.resolve())
                self.assertEqual(load_settings()["app"]["name"], "V test")

    def test_default_configuration(self):
        settings = load_settings()
        self.assertEqual(settings["app"]["name"], "V")
        self.assertEqual(settings["llm"]["provider"], "lm_studio")
        self.assertEqual(
            settings["llm"]["model"],
            "HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive",
        )
        self.assertEqual(
            settings["llm"]["base_url"],
            "http://127.0.0.1:1234/v1",
        )
        self.assertFalse(settings["privacy"]["telemetry_enabled"])
        self.assertFalse(settings["privacy"]["cloud_ai_fallback"])


if __name__ == "__main__":
    unittest.main()
