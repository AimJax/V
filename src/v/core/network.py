"""Central network policy and URL validation for V."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
EXTERNAL_FEATURES = frozenset({"web_search", "web_retrieval"})


class NetworkPolicyError(PermissionError):
    """Raised when an outbound request violates V's network policy."""


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
    """Authorize loopback inference and fail closed for external networking.

    This is an application-level policy. It does not replace Windows Firewall
    or prevent unrelated processes from accessing the network.
    """

    offline_mode: bool = False
    web_search_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: dict) -> "NetworkPolicy":
        if not isinstance(settings, dict):
            raise TypeError("Application settings must be a dictionary.")

        privacy = settings.get("privacy", {})
        web_search = settings.get("web_search", {})

        if not isinstance(privacy, dict) or not isinstance(web_search, dict):
            raise ValueError("Network policy settings sections must be tables.")

        offline_mode = privacy.get("offline_mode", False)
        web_search_enabled = web_search.get("enabled", False)

        if type(offline_mode) is not bool:
            raise ValueError("privacy.offline_mode must be a boolean.")

        if type(web_search_enabled) is not bool:
            raise ValueError("web_search.enabled must be a boolean.")

        return cls(
            offline_mode=offline_mode,
            web_search_enabled=web_search_enabled,
        )

    @property
    def mode_label(self) -> str:
        if self.offline_mode:
            return "OFFLINE"
        if self.web_search_enabled:
            return "ONLINE (web configured; external transport unavailable)"
        return "ONLINE (web access disabled)"

    def authorize_local_endpoint(self, url: str) -> str:
        """Allow validated loopback inference, including in offline mode."""
        return validate_local_http_url(url)

    def authorize_external_url(self, url: str, *, feature: str) -> str:
        """Fail closed until V has a hardened outbound HTTP transport."""
        if feature not in EXTERNAL_FEATURES:
            raise NetworkPolicyError(
                f"External network feature is not permitted: {feature!r}."
            )

        if self.offline_mode:
            raise NetworkPolicyError(
                "External network access is disabled by offline mode."
            )

        if not self.web_search_enabled:
            raise NetworkPolicyError(
                "Web access is disabled. Enable web_search.enabled explicitly."
            )

        if not isinstance(url, str):
            raise TypeError("External URL must be a string.")

        raise NetworkPolicyError(
            "External requests are blocked until V's secure outbound "
            "transport is implemented."
        )
