import io
import unittest

from contextlib import redirect_stdout
from unittest.mock import patch

from v.core.network import (
    NetworkPolicy,
    NetworkPolicyError,
    validate_local_http_url,
)
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

    def test_local_inference_remains_allowed_in_offline_mode(self):
        policy = NetworkPolicy(
            offline_mode=True,
            web_search_enabled=True,
        )

        self.assertEqual(
            policy.authorize_local_endpoint("http://127.0.0.1:1234/v1"),
            "http://127.0.0.1:1234/v1",
        )

        with self.assertRaises(NetworkPolicyError):
            policy.authorize_external_url(
                "https://search.example.com/",
                feature="web_search",
            )

    def test_external_access_requires_explicit_enablement(self):
        policy = NetworkPolicy(
            offline_mode=False,
            web_search_enabled=False,
        )

        with self.assertRaises(NetworkPolicyError):
            policy.authorize_external_url(
                "https://search.example.com/",
                feature="web_search",
            )

    def test_external_access_fails_closed_when_enabled(self):
        policy = NetworkPolicy(
            offline_mode=False,
            web_search_enabled=True,
        )

        with self.assertRaisesRegex(
            NetworkPolicyError,
            "secure outbound transport is implemented",
        ):
            policy.authorize_external_url(
                "https://search.example.com/",
                feature="web_search",
            )

    def test_only_web_search_and_retrieval_features_are_permitted(self):
        policy = NetworkPolicy(
            offline_mode=False,
            web_search_enabled=True,
        )

        with self.assertRaises(NetworkPolicyError):
            policy.authorize_external_url(
                "https://search.example.com/",
                feature="arbitrary_http",
            )

    def test_all_external_destinations_fail_closed(self):
        policy = NetworkPolicy(
            offline_mode=False,
            web_search_enabled=True,
        )

        destinations = [
            "https://search.example.com/",
            "http://search.example.com/",
            "https://127.0.0.1/",
            "https://192.168.1.1/",
        ]

        for url in destinations:
            with self.subTest(url=url):
                with self.assertRaises(NetworkPolicyError):
                    policy.authorize_external_url(
                        url,
                        feature="web_retrieval",
                    )

    def test_policy_loads_settings_and_validates_boolean_types(self):
        policy = NetworkPolicy.from_settings({
            "privacy": {"offline_mode": True},
            "web_search": {"enabled": False},
        })

        self.assertTrue(policy.offline_mode)
        self.assertFalse(policy.web_search_enabled)
        self.assertEqual(policy.mode_label, "OFFLINE")

        with self.assertRaises(ValueError):
            NetworkPolicy.from_settings({
                "privacy": {"offline_mode": "false"},
                "web_search": {"enabled": False},
            })

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
