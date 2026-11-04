"""Factory for supported local OpenAI-compatible chat backends."""

from __future__ import annotations

from typing import Any

from v.providers.base import ChatProvider
from v.providers.lm_studio import OpenAICompatibleLocalProvider

_LOCAL_BACKENDS = {"lm_studio", "llama_cpp", "openai_compatible_local"}


def create_chat_provider(settings: dict[str, Any]) -> ChatProvider:
    """Build a loopback-only provider from the [llm] settings section."""
    backend = str(settings.get("provider", "lm_studio")).strip().lower()
    if backend not in _LOCAL_BACKENDS:
        raise ValueError(
            f"Unsupported local chat provider '{backend}'. "
            f"Supported providers: {', '.join(sorted(_LOCAL_BACKENDS))}."
        )

    return OpenAICompatibleLocalProvider(
        base_url=str(settings.get("base_url", "http://127.0.0.1:1234/v1")),
        model=str(settings.get("model", "")),
        timeout_seconds=float(settings.get("request_timeout_seconds", 120)),
    )
