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

    def test_policy_loads_settings_and_validates_boolean_types(self):
        policy = NetworkPolicy.from_settings({
            "privacy": {"offline_mode": True},
            "web_search": {"enabled": False, "allowed_hosts": []},
            "web_retrieval": {"enabled": False},
        })

        self.assertTrue(policy.offline_mode)
        self.assertFalse(policy.web_search_enabled)
        self.assertFalse(policy.web_retrieval_enabled)
        self.assertEqual(policy.mode_label, "OFFLINE")

        with self.assertRaises(ValueError):
            NetworkPolicy.from_settings({
                "privacy": {"offline_mode": "false"},
                "web_search": {"enabled": False, "allowed_hosts": []},
                "web_retrieval": {"enabled": False},
            })

    def test_search_requires_explicit_host_allowlist(self):
        policy = NetworkPolicy(
            offline_mode=False,
            web_search_enabled=True,
            web_search_allowed_hosts=("api.search.example.com",),
        )

        self.assertEqual(
            policy.authorize_external_url(
                "https://api.search.example.com/v1/search?q=test",
                feature="web_search",
            ),
            "https://api.search.example/v1/search?q=test",
        )

        with self.assertRaises(NetworkPolicyError):
            policy.authorize_external_url(
                "https://other.example.com/v1/search?q=test",
                feature="web_search",
            )

    def test_retrieval_requires_separate_opt_in(self):
        policy = NetworkPolicy()

        with self.assertRaises(NetworkPolicyError):
            policy.authorize_external_url(
                "https://www.example.com/article",
                feature="web_retrieval",
            )

    def test_offline_mode_overrides_enabled_web_features(self):
        policy = NetworkPolicy(
            offline_mode=True,
            web_search_enabled=True,
            web_search_allowed_hosts=("api.search.example",),
            web_retrieval_enabled=True,
        )

        self.assertEqual(
            policy.authorize_local_endpoint("http://127.0.0.1:1234/v1"),
            "http://127.0.0.1:1234/v1",
        )

        for feature, url in (
            ("web_search", "https://api.search.example/search"),
            ("web_retrieval", "https://www.example.com/article"),
        ):
            with self.subTest(feature=feature):
                with self.assertRaises(NetworkPolicyError):
                    policy.authorize_external_url(url, feature=feature)

    def test_search_allowlist_must_be_an_array(self):
        with self.assertRaises(ValueError):
            NetworkPolicy.from_settings({
                "privacy": {"offline_mode": False},
                "web_search": {
                    "enabled": True,
                    "allowed_hosts": "api.search.example",
                },
            })

    def test_search_allowlist_rejects_invalid_hostnames(self):
        with self.assertRaises(NetworkPolicyError):
            NetworkPolicy.from_settings({
                "privacy": {"offline_mode": False},
                "web_search": {
                    "enabled": True,
                    "allowed_hosts": ["127.0.0.1"],
                },
            })

    def test_external_urls_require_https_and_standard_port(self):
        policy = NetworkPolicy(web_retrieval_enabled=True)

        rejected = [
            "http://www.example.com/",
            "https://www.example.com:8443/",
            "https://user:password@www.example.com/",
            "https://127.0.0.1/",
            "https://localhost/",
            "https://service.local/",
            "https://www.example.com/#fragment",
            "https://www.example.com\\path",
        ]

        for url in rejected:
            with self.subTest(url=url):
                with self.assertRaises((ValueError, NetworkPolicyError)):
                    policy.authorize_external_url(
                        url,
                        feature="web_retrieval",
                    )

    def test_diagnostics_refuses_remote_endpoint_before_network_access(self):
        settings = {
            "llm": {
                "provider": "lm_studio",
                "base_url": "https://example.com/v1",
            },
            "privacy": {"offline_mode": True},
            "web_search": {"enabled": False, "allowed_hosts": []},
            "web_retrieval": {"enabled": False},
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
