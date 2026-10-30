import os
import unittest

from pathlib import Path
from unittest.mock import patch

from support import temporary_directory
from v.core.config import load_settings, project_root


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def test_project_root_defaults_to_repository_location(self):
        with patch.dict(os.environ, {"V_HOME": ""}):
            self.assertEqual(project_root(), REPOSITORY_ROOT)

    def test_project_root_honors_v_home_override(self):
        with temporary_directory() as temporary_root:
            with patch.dict(os.environ, {"V_HOME": temporary_root}):
                self.assertEqual(
                    project_root(),
                    Path(temporary_root).resolve(),
                )

    def test_default_configuration(self):
        with patch.dict(os.environ, {"V_HOME": str(REPOSITORY_ROOT)}):
            settings = load_settings()

        self.assertEqual(settings["app"]["name"], "V")
        self.assertEqual(settings["llm"]["provider"], "lm_studio")
        self.assertEqual(
            settings["llm"]["base_url"],
            "http://127.0.0.1:1234/v1",
        )
        self.assertFalse(settings["privacy"]["telemetry_enabled"])
        self.assertFalse(settings["privacy"]["cloud_ai_fallback"])


if __name__ == "__main__":
    unittest.main()
