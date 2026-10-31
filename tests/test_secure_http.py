import socket
import unittest

from unittest.mock import patch

from v.core.network import NetworkPolicy, NetworkPolicyError
from v.core.secure_http import (
    ExternalRequestError,
    PublicOnlyResolver,
    SecureWebClient,
    WebResponse,
    validate_public_ip,
)


class FakeLoop:
    def __init__(self, records):
        self.records = records
        self.calls = []

    async def getaddrinfo(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.records


def dns_record(address, port=443):
    ip_family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (
        (address, port, 0, 0)
        if ip_family == socket.AF_INET6
        else (address, port)
    )
    return (
        ip_family,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        sockaddr,
    )


class PublicAddressValidationTests(unittest.TestCase):
    def test_accepts_public_ipv4_and_ipv6_addresses(self):
        for address in ("1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"):
            with self.subTest(address=address):
                self.assertTrue(validate_public_ip(address).is_global)

    def test_rejects_non_public_and_special_addresses(self):
        rejected = (
            "0.0.0.0",
            "10.0.0.1",
            "100.64.0.1",
            "127.0.0.1",
            "169.254.1.1",
            "192.168.1.1",
            "224.0.0.1",
            "255.255.255.255",
            "::",
            "::1",
            "fc00::1",
            "fe80::1",
            "ff02::1",
            "::ffff:192.168.1.1",
        )

        for address in rejected:
            with self.subTest(address=address):
                with self.assertRaises(NetworkPolicyError):
                    validate_public_ip(address)

    def test_rejects_scoped_ipv6_addresses(self):
        with self.assertRaises(NetworkPolicyError):
            validate_public_ip("fe80::1%12")


class PublicOnlyResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_only_validated_numeric_addresses(self):
        fake_loop = FakeLoop([
            dns_record("1.1.1.1"),
            dns_record("2606:4700:4700::1111"),
        ])
        resolver = PublicOnlyResolver("www.example.com")

        with patch("v.core.secure_http.asyncio.get_running_loop", return_value=fake_loop):
            results = await resolver.resolve("www.example.com", 443)

        self.assertEqual(
            {item["host"] for item in results},
            {"1.1.1.1", "2606:4700:4700::1111"},
        )
        self.assertTrue(all(item["flags"] == socket.AI_NUMERICHOST for item in results))
        self.assertEqual(len(fake_loop.calls), 1)

        await resolver.close()

    async def test_rejects_mixed_public_and_private_dns_answers(self):
        fake_loop = FakeLoop([
            dns_record("1.1.1.1"),
            dns_record("127.0.0.1"),
        ])
        resolver = PublicOnlyResolver("www.example.com")

        with (
            patch("v.core.secure_http.asyncio.get_running_loop", return_value=fake_loop),
            self.assertRaises(NetworkPolicyError),
        ):
            await resolver.resolve("www.example.com", 443)

    async def test_rejects_unexpected_hostname(self):
        resolver = PublicOnlyResolver("www.example.com")

        with self.assertRaises(NetworkPolicyError):
            await resolver.resolve("attacker.example", 443)

    async def test_rejects_resolution_after_close(self):
        resolver = PublicOnlyResolver("www.example.com")
        await resolver.close()

        with self.assertRaises(RuntimeError):
            await resolver.resolve("www.example.com", 443)


class StubSecureWebClient(SecureWebClient):
    def __init__(self, policy, responses, **kwargs):
        super().__init__(policy, **kwargs)
        self.responses = list(responses)
        self.requested_urls = []

    async def _get_once(self, url):
        self.requested_urls.append(url)
        return self.responses.pop(0)


class SecureWebClientRedirectTests(unittest.IsolatedAsyncioTestCase):
    def retrieval_policy(self):
        return NetworkPolicy(web_retrieval_enabled=True)

    async def test_returns_non_redirect_response(self):
        expected = WebResponse(
            url="https://www.example.com/page",
            status_code=200,
            headers={"content-type": "text/html", "location": ""},
            body=b"<html>ok</html>",
        )
        client = StubSecureWebClient(self.retrieval_policy(), [expected])

        response = await client.get(
            expected.url,
            feature="web_retrieval",
        )

        self.assertIs(response, expected)
        self.assertEqual(client.requested_urls, [expected.url])

    async def test_reauthorizes_redirect_before_second_request(self):
        first = WebResponse(
            url="https://www.example.com/page",
            status_code=302,
            headers={"location": "https://127.0.0.1/admin"},
            body=b"",
        )
        client = StubSecureWebClient(self.retrieval_policy(), [first])

        with self.assertRaises(NetworkPolicyError):
            await client.get(first.url, feature="web_retrieval")

        self.assertEqual(client.requested_urls, [first.url])

    async def test_rejects_redirect_to_http(self):
        first = WebResponse(
            url="https://www.example.com/page",
            status_code=301,
            headers={"location": "http://www.example.com/"},
            body=b"",
        )
        client = StubSecureWebClient(self.retrieval_policy(), [first])

        with self.assertRaises(NetworkPolicyError):
            await client.get(first.url, feature="web_retrieval")

    async def test_rejects_redirect_loop(self):
        first = WebResponse(
            url="https://www.example.com/page",
            status_code=302,
            headers={"location": "/page"},
            body=b"",
        )
        client = StubSecureWebClient(
            self.retrieval_policy(),
            [first, first],
        )

        with self.assertRaisesRegex(ExternalRequestError, "Redirect loop"):
            await client.get(first.url, feature="web_retrieval")

        self.assertEqual(client.requested_urls, [first.url])

    async def test_enforces_redirect_limit(self):
        first = WebResponse(
            url="https://www.example.com/a",
            status_code=302,
            headers={"location": "/b"},
            body=b"",
        )
        second = WebResponse(
            url="https://www.example.com/b",
            status_code=302,
            headers={"location": "/c"},
            body=b"",
        )
        client = StubSecureWebClient(
            self.retrieval_policy(),
            [first, second],
            max_redirects=1,
        )

        with self.assertRaisesRegex(ExternalRequestError, "Maximum redirect"):
            await client.get(first.url, feature="web_retrieval")

        self.assertEqual(client.requested_urls, [
            "https://www.example.com/a",
            "https://www.example.com/b",
        ])


if __name__ == "__main__":
    unittest.main()
