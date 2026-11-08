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
    "vision_model",
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
    "voice_enabled",
    "voice_wake_phrase",
    "voice_input_device_id",
    "voice_output_device_id",
    "voice_sample_rate",
    "voice_stt_language",
    "voice_stt_device",
    "voice_stt_threads",
    "voice_whisper_cuda_server_path",
    "voice_whisper_server_path",
    "voice_whisper_model_path",
    "voice_silero_vad_model_path",
    "voice_vad_threshold",
    "voice_vad_min_speech_duration_ms",
    "voice_vad_silence_duration_ms",
    "voice_max_utterance_seconds",
    "voice_kokoro_model_path",
    "voice_kokoro_voices_path",
    "voice_kokoro_voice",
    "voice_tts_speed",
    "voice_speak_replies",
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


def _require_string(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    maximum: int = 512,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValueError(f"{name} cannot be empty.")
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters.")
    return normalized


def _require_project_path(value: Any, name: str) -> str:
    normalized = _require_string(value, name)
    candidate = Path(normalized).expanduser()
    root = project_root().resolve()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{name} must remain inside the V project directory.")
    return normalized


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

    normalized["vision_model"] = _require_string(
        normalized["vision_model"], "Vision model", allow_empty=True
    )
    if normalized["vision_model"] and normalized["vision_model"] not in available_models:
        raise ValueError(
            f"Vision model '{normalized['vision_model']}' is not loaded in LM Studio."
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

    normalized["voice_enabled"] = _require_bool(
        normalized["voice_enabled"], "Voice enabled"
    )
    normalized["voice_speak_replies"] = _require_bool(
        normalized["voice_speak_replies"], "Speak replies"
    )
    if normalized["voice_speak_replies"] and not normalized["voice_enabled"]:
        raise ValueError("Enable voice interaction before enabling spoken replies.")
    normalized["voice_wake_phrase"] = _require_string(
        normalized["voice_wake_phrase"], "Wake phrase", maximum=80
    )
    for field, name in (
        ("voice_input_device_id", "Microphone device ID"),
        ("voice_output_device_id", "Speaker device ID"),
    ):
        device_id = _require_string(
            normalized[field], name, allow_empty=True, maximum=256
        )
        if device_id and (
            len(device_id) % 2
            or any(character not in "0123456789abcdefABCDEF" for character in device_id)
        ):
            raise ValueError(f"{name} must be an audio device ID in hexadecimal form.")
        normalized[field] = device_id.casefold()

    normalized["voice_sample_rate"] = _require_int(
        normalized["voice_sample_rate"], "Voice sample rate", 16000, 16000
    )
    normalized["voice_stt_language"] = _require_string(
        normalized["voice_stt_language"], "Speech recognition language", maximum=12
    ).casefold()
    if normalized["voice_stt_language"] not in {"auto", "en", "id"}:
        raise ValueError("Speech recognition language must be auto, en, or id.")

    normalized["voice_stt_device"] = _require_string(
        normalized["voice_stt_device"], "Speech recognition device", maximum=8
    ).casefold()
    if normalized["voice_stt_device"] not in {"cpu", "cuda"}:
        raise ValueError("Speech recognition device must be cpu or cuda.")

    normalized["voice_stt_threads"] = _require_int(
        normalized["voice_stt_threads"], "Speech recognition threads", 1, 8
    )

    for field, name in (
        ("voice_whisper_server_path", "Whisper CPU server path"),
        ("voice_whisper_cuda_server_path", "Whisper CUDA server path"),
        ("voice_whisper_model_path", "Whisper model path"),
        ("voice_silero_vad_model_path", "Silero VAD model path"),
        ("voice_kokoro_model_path", "Kokoro ONNX model path"),
        ("voice_kokoro_voices_path", "Kokoro voices file path"),
    ):
        normalized[field] = _require_project_path(normalized[field], name)

    normalized["voice_vad_threshold"] = _require_float(
        normalized["voice_vad_threshold"], "VAD threshold", 0.1, 0.95
    )
    normalized["voice_vad_min_speech_duration_ms"] = _require_int(
        normalized["voice_vad_min_speech_duration_ms"],
        "VAD minimum speech duration",
        50,
        2000,
    )
    normalized["voice_vad_silence_duration_ms"] = _require_int(
        normalized["voice_vad_silence_duration_ms"],
        "VAD silence duration",
        100,
        3000,
    )
    normalized["voice_max_utterance_seconds"] = _require_int(
        normalized["voice_max_utterance_seconds"],
        "Maximum voice utterance",
        5,
        120,
    )
    normalized["voice_kokoro_voice"] = _require_string(
        normalized["voice_kokoro_voice"], "Kokoro voice ID", maximum=48
    )
    normalized["voice_tts_speed"] = _require_float(
        normalized["voice_tts_speed"], "TTS speed", 0.5, 2.0
    )

    if normalized["voice_enabled"]:
        selected_server_field = (
            "voice_whisper_cuda_server_path"
            if normalized["voice_stt_device"] == "cuda"
            else "voice_whisper_server_path"
        )
        selected_server_label = (
            "Whisper CUDA server executable"
            if normalized["voice_stt_device"] == "cuda"
            else "Whisper CPU server executable"
        )
        required_voice_assets = [
            (selected_server_field, selected_server_label),
            ("voice_whisper_model_path", "Whisper model"),
            ("voice_silero_vad_model_path", "Silero VAD model"),
        ]
        if normalized["voice_speak_replies"]:
            required_voice_assets.extend([
                ("voice_kokoro_model_path", "Kokoro ONNX model"),
                ("voice_kokoro_voices_path", "Kokoro voice file"),
            ])
        root = project_root().resolve()
        for field, label in required_voice_assets:
            candidate = Path(normalized[field]).expanduser()
            candidate = (
                candidate.resolve()
                if candidate.is_absolute()
                else (root / candidate).resolve()
            )
            if not candidate.is_file():
                raise FileNotFoundError(
                    f"{label} is not installed at the configured path: {candidate}"
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
    voice_values = {
        "enabled": normalized["voice_enabled"],
        "wake_phrase": normalized["voice_wake_phrase"],
        "input_device_id": normalized["voice_input_device_id"],
        "output_device_id": normalized["voice_output_device_id"],
        "sample_rate": normalized["voice_sample_rate"],
        "stt_language": normalized["voice_stt_language"],
        "stt_device": normalized["voice_stt_device"],
        "stt_threads": normalized["voice_stt_threads"],
        "whisper_server_path": normalized["voice_whisper_server_path"],
        "whisper_cuda_server_path": normalized["voice_whisper_cuda_server_path"],
        "whisper_model_path": normalized["voice_whisper_model_path"],
        "silero_vad_model_path": normalized["voice_silero_vad_model_path"],
        "vad_threshold": normalized["voice_vad_threshold"],
        "vad_min_speech_duration_ms": normalized["voice_vad_min_speech_duration_ms"],
        "vad_silence_duration_ms": normalized["voice_vad_silence_duration_ms"],
        "max_utterance_seconds": normalized["voice_max_utterance_seconds"],
        "kokoro_model_path": normalized["voice_kokoro_model_path"],
        "kokoro_voices_path": normalized["voice_kokoro_voices_path"],
        "kokoro_voice": normalized["voice_kokoro_voice"],
        "tts_speed": normalized["voice_tts_speed"],
        "speak_replies": normalized["voice_speak_replies"],
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
        ("voice", voice_values),
        ("vision", {"model": normalized["vision_model"]}),
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
