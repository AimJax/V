import unittest

from v.core.config import load_settings, project_root


class ConfigurationTests(unittest.TestCase):
    def test_project_root(self):
        self.assertEqual(str(project_root()).lower(), r"g:\v")

    def test_default_configuration(self):
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