"""Central network policy and URL validation for V."""

from __future__ import annotations

import ipaddress
import re

from dataclasses import dataclass
from urllib.parse import urlsplit


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
EXTERNAL_FEATURES = frozenset({"web_search", "web_retrieval"})
SPECIAL_HOST_SUFFIXES = (
    ".localhost", ".local", ".internal", ".home.arpa",
    ".onion", ".test", ".invalid", ".example", ".arpa",
)
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class NetworkPolicyError(PermissionError):
    """Raised when an outbound request violates V's network policy."""


def normalize_external_hostname(hostname: str) -> str:
    """Return a strict ASCII DNS hostname, rejecting local names and IP literals."""
    if not isinstance(hostname, str):
        raise TypeError("External hostname must be a string.")

    if (
        not hostname
        or hostname.endswith(".")
        or any(character in hostname for character in "/\\:@[]%")
        or any(character.isspace() for character in hostname)
    ):
        raise NetworkPolicyError("Invalid external hostname.")

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise NetworkPolicyError(
            "External URL literals are not permitted; use a public hostname."
        )

    try:
        normalized = hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise NetworkPolicyError("External hostname is not valid IDNA.") from error

    if len(normalized) > 253 or "." not in normalized:
        raise NetworkPolicyError("External hostname must be a fully qualified DNS name.")

    labels = normalized.split(".")

    if any(
        not label
        or len(label) > 63
        or _HOST_LABEL.fullmatch(label) is None
        for label in labels
    ):
        raise NetworkPolicyError("External hostname contains an invalid DNS label.")

    if normalized in LOOPBACK_HOSTS or normalized.endswith(SPECIAL_HOST_SUFFIXES):
        raise NetworkPolicyError("Local or special-use hostnames are not permitted.")

    return normalized


def validate_local_http_url(url: str) -> str:
    """Validate and normalize an HTTP endpoint restricted to loopback."""
    if not isinstance(url, str):
        raise TypeError("Local endpoint URL must be a string.")

    value = url.strip()

    if not value or any(character.isspace() for character in value):
        raise ValueError("Local endpoint URL is empty or contains whitespace.")

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError as error:
        raise ValueError(f"Invalid local endpoint URL: {error}") from error

    if (
        parsed.scheme != "http"
        or hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Endpoint must use HTTP on localhost, 127.0.0.1, or ::1, "
            "without credentials, query parameters, or fragments."
        )

    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Authorize local inference and explicitly enabled public web access.

    DNS/IP validation and connection pinning are performed by SecureWebClient.
    This is an application-level policy, not a Windows Firewall rule.
    """

    offline_mode: bool = False
    web_search_enabled: bool = False
    web_search_allowed_hosts: tuple[str, ...] = ()
    web_retrieval_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: dict) -> "NetworkPolicy":
        if not isinstance(settings, dict):
            raise TypeError("Application settings must be a dictionary.")

        privacy = settings.get("privacy", {})
        web_search = settings.get("web_search", {})
        web_retrieval = settings.get("web_retrieval", {})

        if (
            not isinstance(privacy, dict)
            or not isinstance(web_search, dict)
            or not isinstance(web_retrieval, dict)
        ):
            raise ValueError("Network policy settings sections must be tables.")

        offline_mode = privacy.get("offline_mode", False)
        web_search_enabled = web_search.get("enabled", False)
        web_retrieval_enabled = web_retrieval.get("enabled", False)
        allowed_hosts = web_search.get("allowed_hosts", [])

        if type(offline_mode) is not bool:
            raise ValueError("privacy.offline_mode must be a boolean.")

        if type(web_search_enabled) is not bool:
            raise ValueError("web_search.enabled must be a boolean.")

        if type(web_retrieval_enabled) is not bool:
            raise ValueError("web_retrieval.enabled must be a boolean.")

        if not isinstance(allowed_hosts, list) or any(
            not isinstance(host, str) for host in allowed_hosts
        ):
            raise ValueError("web_search.allowed_hosts must be an array of hostnames.")

        normalized_hosts = tuple(
            dict.fromkeys(normalize_external_hostname(host) for host in allowed_hosts)
        )

        return cls(
            offline_mode=offline_mode,
            web_search_enabled=web_search_enabled,
            web_search_allowed_hosts=normalized_hosts,
            web_retrieval_enabled=web_retrieval_enabled,
        )

    @property
    def mode_label(self) -> str:
        if self.offline_mode:
            return "OFFLINE"

        enabled = []
        if self.web_search_enabled:
            enabled.append("search")
        if self.web_retrieval_enabled:
            enabled.append("retrieval")

        if not enabled:
            return "ONLINE (web access disabled)"

        return f"ONLINE (web {' and '.join(enabled)} enabled)"

    def authorize_local_endpoint(self, url: str) -> str:
        """Allow validated loopback inference, including in offline mode."""
        return validate_local_http_url(url)

    def authorize_external_url(self, url: str, *, feature: str) -> str:
        """Check feature settings and URL syntax before pinned DNS resolution."""
        if feature not in EXTERNAL_FEATURES:
            raise NetworkPolicyError(
                f"External network feature is not permitted: {feature!r}."
            )

        if self.offline_mode:
            raise NetworkPolicyError(
                "External network access is disabled by offline mode."
            )

        if feature == "web_search" and not self.web_search_enabled:
            raise NetworkPolicyError("Web search is disabled in configuration.")

        if feature == "web_retrieval" and not self.web_retrieval_enabled:
            raise NetworkPolicyError("Web retrieval is disabled in configuration.")

        if not isinstance(url, str):
            raise TypeError("External URL must be a string.")

        value = url.strip()

        if (
            not value
            or len(value) > 8192
            or any(character.isspace() for character in value)
            or "\\" in value
        ):
            raise ValueError("External URL is empty, too long, or malformed.")

        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise ValueError(f"Invalid external URL: {error}") from error

        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port not in (None, 443)
        ):
            raise NetworkPolicyError(
                "External destinations must use HTTPS on port 443, "
                "without credentials or fragments."
            )

        normalized_host = normalize_external_hostname(hostname)

        if (
            feature == "web_search"
            and normalized_host not in self.web_search_allowed_hosts
        ):
            raise NetworkPolicyError(
                "Search endpoint hostname is not in web_search.allowed_hosts."
            )

        return value
