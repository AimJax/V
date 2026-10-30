import io
import unittest

from contextlib import redirect_stdout
from unittest.mock import patch

from v.core.network import validate_local_http_url
from v.diagnostics import main


class LocalEndpointValidationTests(unittest.TestCase):
    def test_accepts_loopback_endpoints(self):
        cases = {
            "http://127.0.0.1:1234/v1/": "http://127.0.0.1:1234/v1",
            "http://localhost:1234/v1": "http://localhost:1234/v1",
            "http://[::1]:1234/v1": "http://[::1]:1234/v1",
        }

        for supplied, expected in cases.items():
            with self.subTest(url=supplied):
                self.assertEqual(validate_local_http_url(supplied), expected)

    def test_rejects_non_local_and_unsafe_endpoints(self):
        rejected = [
            "https://127.0.0.1:1234/v1",
            "http://example.com/v1",
            "http://127.0.0.1.example.com/v1",
            "http://user:password@localhost:1234/v1",
            "http://localhost:99999/v1",
            "http://localhost:1234/v1?token=value",
            "http://localhost:1234/v1#fragment",
        ]

        for supplied in rejected:
            with self.subTest(url=supplied):
                with self.assertRaises(ValueError):
                    validate_local_http_url(supplied)

    def test_rejects_non_string_endpoint(self):
        with self.assertRaises(TypeError):
            validate_local_http_url(None)

    def test_diagnostics_refuses_remote_endpoint_before_network_access(self):
        settings = {
            "llm": {
                "provider": "lm_studio",
                "base_url": "https://example.com/v1",
            }
        }
        output = io.StringIO()

        with (
            patch("v.diagnostics.load_settings", return_value=settings),
            patch("v.diagnostics.httpx.Client") as client,
            redirect_stdout(output),
        ):
            result = main()

        self.assertEqual(result, 1)
        client.assert_not_called()
        self.assertIn("REFUSED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
