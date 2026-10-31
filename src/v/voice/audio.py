"""PCM conversion and WAV packaging for local microphone input."""

from __future__ import annotations

import io
import math
import sys
import wave

from array import array


TARGET_SAMPLE_RATE = 16000
MAX_AUDIO_SECONDS = 120


def _decode_samples(raw: bytes, sample_format: str) -> list[float]:
    normalized = sample_format.casefold()

    if normalized in {"int16", "qtaudioformat.sampleformat.int16"}:
        values = array("h")
        values.frombytes(raw[: len(raw) - len(raw) % values.itemsize])
        if sys.byteorder != "little":
            values.byteswap()
        scale = 1.0 / 32768.0
        return [max(-1.0, min(1.0, value * scale)) for value in values]

    if normalized in {"uint8", "qtaudioformat.sampleformat.uint8"}:
        return [(value - 128) / 128.0 for value in raw]

    if normalized in {"int32", "qtaudioformat.sampleformat.int32"}:
        values = array("i")
        values.frombytes(raw[: len(raw) - len(raw) % values.itemsize])
        if sys.byteorder != "little":
            values.byteswap()
        scale = 1.0 / 2147483648.0
        return [max(-1.0, min(1.0, value * scale)) for value in values]

    if normalized in {"float", "float32", "qtaudioformat.sampleformat.float"}:
        values = array("f")
        values.frombytes(raw[: len(raw) - len(raw) % values.itemsize])
        if sys.byteorder != "little":
            values.byteswap()
        return [
            max(-1.0, min(1.0, value if math.isfinite(value) else 0.0))
            for value in values
        ]

    raise ValueError(f"Unsupported audio sample format: {sample_format!r}")


def _downmix(samples: list[float], channels: int) -> list[float]:
    if channels < 1:
        raise ValueError("Audio must contain at least one channel.")

    complete_frames = len(samples) // channels
    if complete_frames == 0:
        return []

    if channels == 1:
        return samples[:complete_frames]

    mono: list[float] = []
    for frame in range(complete_frames):
        start = frame * channels
        mono.append(sum(samples[start : start + channels]) / channels)
    return mono


def _resample_linear(
    samples: list[float],
    source_rate: int,
    target_rate: int,
) -> list[float]:
    if source_rate == target_rate:
        return samples

    if not samples:
        return []

    target_count = max(1, round(len(samples) * target_rate / source_rate))
    last_index = len(samples) - 1
    output: list[float] = []

    for target_index in range(target_count):
        position = target_index * source_rate / target_rate
        left = min(int(position), last_index)
        right = min(left + 1, last_index)
        fraction = position - left
        output.append(
            samples[left] + (samples[right] - samples[left]) * fraction
        )

    return output


def pcm_to_wav_16khz_mono(
    raw: bytes,
    *,
    sample_rate: int,
    channels: int,
    sample_format: str,
    max_seconds: int = MAX_AUDIO_SECONDS,
) -> bytes:
    """Convert Qt PCM formats to a bounded 16 kHz mono PCM16 WAV payload."""
    if not isinstance(raw, bytes) or not raw:
        raise ValueError("Audio input is empty.")

    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
        raise ValueError("Audio sample rate must be an integer.")
    if sample_rate < 8000 or sample_rate > 192000:
        raise ValueError("Audio sample rate must be between 8 and 192 kHz.")
    if isinstance(channels, bool) or not isinstance(channels, int):
        raise ValueError("Audio channel count must be an integer.")
    if not 1 <= channels <= 8:
        raise ValueError("Audio must contain between 1 and 8 channels.")
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, int):
        raise ValueError("Maximum audio duration must be an integer.")
    if not 1 <= max_seconds <= MAX_AUDIO_SECONDS:
        raise ValueError(f"Maximum audio duration must be between 1 and {MAX_AUDIO_SECONDS} seconds.")

    samples = _decode_samples(raw, sample_format)
    mono = _downmix(samples, channels)
    if not mono:
        raise ValueError("Audio contains no complete sample frames.")

    if len(mono) > sample_rate * max_seconds:
        raise ValueError(f"Audio exceeds the {max_seconds}-second limit.")

    resampled = _resample_linear(mono, sample_rate, TARGET_SAMPLE_RATE)
    pcm = array(
        "h",
        (
            max(-32768, min(32767, round(value * 32767.0)))
            for value in resampled
        ),
    )
    if sys.byteorder != "little":
        pcm.byteswap()

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(TARGET_SAMPLE_RATE)
        writer.writeframes(pcm.tobytes())
    return buffer.getvalue()
