"""SSRF-resistant, bounded HTTPS GET transport for public web resources."""

from __future__ import annotations

import asyncio
import ipaddress
import socket

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp

from aiohttp.abc import AbstractResolver

from v.core.network import (
    NetworkPolicy,
    NetworkPolicyError,
    normalize_external_hostname,
)


class ExternalRequestError(RuntimeError):
    """Raised when a secure external HTTP request fails."""


@dataclass(frozen=True, slots=True)
class WebResponse:
    """Bounded response data safe to pass to higher-level parsers."""

    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes


def validate_public_ip(address_text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Reject every non-public or special-purpose destination address."""
    if not isinstance(address_text, str) or "%" in address_text:
        raise NetworkPolicyError("DNS returned an invalid or scoped IP address.")

    try:
        address = ipaddress.ip_address(address_text)
    except ValueError as error:
        raise NetworkPolicyError("DNS returned an invalid IP address.") from error

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped

    if (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise NetworkPolicyError(
            f"DNS resolved to a non-public destination address: {address}."
        )

    return address


class PublicOnlyResolver(AbstractResolver):
    """Resolve one expected hostname and return only validated numeric addresses.

    aiohttp connects to these returned addresses directly while retaining the
    original URL hostname for HTTP Host and TLS certificate/SNI validation.
    """

    def __init__(self, expected_hostname: str) -> None:
        self.expected_hostname = normalize_external_hostname(expected_hostname)
        self._closed = False

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_UNSPEC,
    ) -> list[dict[str, object]]:
        if self._closed:
            raise RuntimeError("DNS resolver is closed.")

        normalized_host = normalize_external_hostname(host)

        if normalized_host != self.expected_hostname:
            raise NetworkPolicyError(
                "DNS resolver was asked to resolve an unexpected hostname."
            )

        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(
            normalized_host,
            port,
            family=family,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )

        results: list[dict[str, object]] = []
        seen: set[tuple[int, str]] = set()

        for address_family, _socket_type, protocol, _canonical_name, sockaddr in records:
            address = validate_public_ip(sockaddr[0])
            key = (address_family, address.compressed)

            if key in seen:
                continue

            seen.add(key)
            results.append({
                "hostname": normalized_host,
                "host": address.compressed,
                "port": port,
                "family": address_family,
                "proto": protocol,
                "flags": socket.AI_NUMERICHOST,
            })

        if not results:
            raise ExternalRequestError(
                f"No public DNS addresses were returned for {normalized_host}."
            )

        return results

    async def close(self) -> None:
        self._closed = True


class SecureWebClient:
    """Fetch public HTTPS resources with DNS pinning and strict resource limits.

    This client exposes GET only. It does not inherit proxy settings, persist
    cookies, follow redirects automatically, or accept caller-supplied headers.
    """

    REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

    def __init__(
        self,
        policy: NetworkPolicy,
        *,
        timeout_seconds: float = 20.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_redirects: int = 5,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("HTTP timeout must be positive.")

        if max_response_bytes < 1:
            raise ValueError("Maximum response size must be positive.")

        if max_redirects < 0:
            raise ValueError("Maximum redirects cannot be negative.")

        self._policy = policy
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)
        self.max_redirects = int(max_redirects)

    async def get(self, url: str, *, feature: str) -> WebResponse:
        """GET a public HTTPS URL, reauthorizing every redirect destination."""
        current_url = self._policy.authorize_external_url(url, feature=feature)
        visited: set[str] = set()

        for redirect_count in range(self.max_redirects + 1):
            if current_url in visited:
                raise ExternalRequestError("Redirect loop detected.")

            visited.add(current_url)
            response = await self._get_once(current_url)

            location = response.headers.get("location")

            if response.status_code not in self.REDIRECT_STATUSES or not location:
                return response

            if redirect_count >= self.max_redirects:
                raise ExternalRequestError("Maximum redirect count exceeded.")

            next_url = urljoin(current_url, location)
            current_url = self._policy.authorize_external_url(
                next_url,
                feature=feature,
            )

        raise ExternalRequestError("Maximum redirect count exceeded.")

    async def _get_once(self, url: str) -> WebResponse:
        """Perform one request with a fresh resolver and connection pool."""
        hostname = urlsplit(url).hostname

        if hostname is None:
            raise NetworkPolicyError("External URL has no hostname.")

        resolver = PublicOnlyResolver(hostname)
        connector = aiohttp.TCPConnector(
            resolver=resolver,
            use_dns_cache=False,
            force_close=True,
            limit=1,
            ssl=True,
        )
        timeout = aiohttp.ClientTimeout(
            total=self.timeout_seconds,
            connect=min(self.timeout_seconds, 5.0),
            sock_connect=min(self.timeout_seconds, 5.0),
            sock_read=min(self.timeout_seconds, 10.0),
        )

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                auto_decompress=True,
                raise_for_status=False,
                max_line_size=8190,
                max_field_size=8190,
            ) as session:
                async with session.get(
                    url,
                    allow_redirects=False,
                    headers={
                        "Accept": (
                            "text/html,application/xhtml+xml,application/json,"
                            "text/plain;q=0.9,*/*;q=0.1"
                        ),
                        "User-Agent": "V-Local-Companion/0.1",
                    },
                ) as response:
                    if (
                        response.content_length is not None
                        and response.content_length > self.max_response_bytes
                    ):
                        raise ExternalRequestError(
                            "External response exceeds the configured size limit."
                        )

                    body = bytearray()

                    async for chunk in response.content.iter_chunked(64 * 1024):
                        if len(body) + len(chunk) > self.max_response_bytes:
                            raise ExternalRequestError(
                                "External response exceeds the configured size limit."
                            )

                        body.extend(chunk)

                    selected_headers = {
                        "content-type": response.headers.get("Content-Type", ""),
                        "location": response.headers.get("Location", ""),
                    }

                    return WebResponse(
                        url=url,
                        status_code=response.status,
                        headers=selected_headers,
                        body=bytes(body),
                    )

        except NetworkPolicyError:
            raise
        except ExternalRequestError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
            raise ExternalRequestError(
                f"External HTTPS request failed: {type(error).__name__}: {error}"
            ) from error
