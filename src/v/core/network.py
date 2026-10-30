"""Shared network-boundary validation for local inference services."""

from __future__ import annotations

from urllib.parse import urlsplit


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
