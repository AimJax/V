"""Validated local settings persistence for V's desktop interface."""

from __future__ import annotations

import math
import os
import tempfile

from pathlib import Path
from typing import Any

import tomlkit

from v.core.config import project_root


SETTING_FIELDS = {
    "model",
    "temperature",
    "max_tokens",
    "history_messages",
    "offline_mode",
    "memory_enabled",
    "automatic_extraction",
    "retrieval_enabled",
    "embedding_model",
    "minimum_confidence",
    "idle_delay_seconds",
    "max_jobs_per_idle_cycle",
    "semantic_threshold",
    "retrieval_limit",
    "retrieval_max_characters",
}


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be enabled or disabled.")
    return value


def _require_int(
    value: Any,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number.")
    if not minimum <= value <= maximum:
        raise ValueError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return value


def _require_float(
    value: Any,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric.")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return number


def validate_desktop_settings(
    changes: dict[str, Any],
    *,
    available_models: list[str],
) -> dict[str, Any]:
    if not isinstance(changes, dict):
        raise TypeError("Settings changes must be a dictionary.")

    unexpected = set(changes) - SETTING_FIELDS
    missing = SETTING_FIELDS - set(changes)
    if unexpected:
        raise ValueError(f"Unsupported settings: {sorted(unexpected)}")
    if missing:
        raise ValueError(f"Missing settings: {sorted(missing)}")

    normalized = dict(changes)

    for field in ("model", "embedding_model"):
        value = normalized[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty model identifier.")
        normalized[field] = value.strip()

    if normalized["model"] not in available_models:
        raise ValueError(
            f"Chat model '{normalized['model']}' is not loaded in LM Studio."
        )

    for field in (
        "offline_mode",
        "memory_enabled",
        "automatic_extraction",
        "retrieval_enabled",
    ):
        normalized[field] = _require_bool(normalized[field], field)

    normalized["temperature"] = _require_float(
        normalized["temperature"], "Temperature", 0.0, 2.0
    )
    normalized["max_tokens"] = _require_int(
        normalized["max_tokens"], "Maximum tokens", 1, 32768
    )
    normalized["history_messages"] = _require_int(
        normalized["history_messages"], "Conversation history", 2, 200
    )
    normalized["minimum_confidence"] = _require_float(
        normalized["minimum_confidence"], "Minimum memory confidence", 0.0, 1.0
    )
    normalized["idle_delay_seconds"] = _require_float(
        normalized["idle_delay_seconds"], "Memory idle delay", 0.0, 3600.0
    )
    normalized["max_jobs_per_idle_cycle"] = _require_int(
        normalized["max_jobs_per_idle_cycle"], "Memory jobs per cycle", 1, 50
    )
    normalized["semantic_threshold"] = _require_float(
        normalized["semantic_threshold"], "Semantic threshold", 0.0, 1.0
    )
    normalized["retrieval_limit"] = _require_int(
        normalized["retrieval_limit"], "Memory retrieval limit", 1, 50
    )
    normalized["retrieval_max_characters"] = _require_int(
        normalized["retrieval_max_characters"],
        "Memory context character limit",
        100,
        20000,
    )

    if normalized["memory_enabled"] and normalized["retrieval_enabled"]:
        if normalized["embedding_model"] not in available_models:
            raise ValueError(
                "The selected embedding model is not loaded in LM Studio. "
                "Load it there or disable semantic retrieval before saving."
            )
        if normalized["embedding_model"] == normalized["model"]:
            raise ValueError(
                "Choose different models for chat and semantic embeddings."
            )

    return normalized


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def save_local_desktop_settings(
    current_settings: dict[str, Any],
    changes: dict[str, Any],
    personality: str,
    *,
    available_models: list[str],
) -> tuple[Path, Path]:
    """Save validated overrides and personality text without replacing unknown settings."""
    if not isinstance(personality, str) or not personality.strip():
        raise ValueError("Personality instructions cannot be empty.")

    normalized = validate_desktop_settings(
        changes,
        available_models=available_models,
    )

    root = project_root().resolve()
    local_path = root / "config" / "local.toml"

    personality_setting = Path(
        current_settings.get("paths", {}).get(
            "personality",
            "config/personality.md",
        )
    )
    personality_path = (
        personality_setting
        if personality_setting.is_absolute()
        else root / personality_setting
    ).resolve()

    if not personality_path.is_relative_to(root):
        raise ValueError(
            "The configured personality file is outside the V project directory."
        )

    existing_text = local_path.read_text(encoding="utf-8") if local_path.is_file() else ""
    document = tomlkit.parse(existing_text) if existing_text.strip() else tomlkit.document()

    llm_values = {
        "model": normalized["model"],
        "temperature": normalized["temperature"],
        "max_tokens": normalized["max_tokens"],
        "history_messages": normalized["history_messages"],
    }
    privacy_values = {
        "offline_mode": normalized["offline_mode"],
    }
    memory_values = {
        "enabled": normalized["memory_enabled"],
        "automatic_extraction": normalized["automatic_extraction"],
        "retrieval_enabled": normalized["retrieval_enabled"],
        "embedding_model": normalized["embedding_model"],
        "minimum_confidence": normalized["minimum_confidence"],
        "idle_delay_seconds": normalized["idle_delay_seconds"],
        "max_jobs_per_idle_cycle": normalized["max_jobs_per_idle_cycle"],
        "semantic_threshold": normalized["semantic_threshold"],
        "retrieval_limit": normalized["retrieval_limit"],
        "retrieval_max_characters": normalized["retrieval_max_characters"],
    }

    for section_name, values in (
        ("llm", llm_values),
        ("privacy", privacy_values),
        ("memory", memory_values),
    ):
        section = document.get(section_name)
        if section is None:
            section = tomlkit.table()
            document[section_name] = section
        for key, value in values.items():
            section[key] = value

    _atomic_write(personality_path, personality)
    _atomic_write(local_path, tomlkit.dumps(document))
    return local_path, personality_path
