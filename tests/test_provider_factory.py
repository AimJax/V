import unittest

from v.providers.factory import create_chat_provider
from v.providers.lm_studio import OpenAICompatibleLocalProvider


class ProviderFactoryTests(unittest.TestCase):
    def test_lm_studio_backend(self):
        provider = create_chat_provider({
            "provider": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "test-model",
        })
        self.assertIsInstance(provider, OpenAICompatibleLocalProvider)
        self.assertEqual(provider.model, "test-model")

    def test_llama_cpp_backend(self):
        provider = create_chat_provider({
            "provider": "llama_cpp",
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "test-model",
        })
        self.assertIsInstance(provider, OpenAICompatibleLocalProvider)
        self.assertEqual(provider.base_url, "http://127.0.0.1:8080/v1")

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ValueError):
            create_chat_provider({"provider": "cloud_provider"})

    def test_non_loopback_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            create_chat_provider({
                "provider": "llama_cpp",
                "base_url": "https://example.com/v1",
                "model": "test-model",
            })


if __name__ == "__main__":
    unittest.main()
