"""Local Kokoro ONNX speech synthesis with in-memory WAV output."""

from __future__ import annotations

import asyncio
import io
import math
import wave

from array import array
from pathlib import Path
from typing import Any


class KokoroSpeechEngine:
    """Load Kokoro once and synthesize speech without writing audio to disk."""

    def __init__(
        self,
        model_path: Path | str,
        voices_path: Path | str,
        *,
        default_voice: str = "af_heart",
    ) -> None:
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self.default_voice = default_voice
        self._engine: Any | None = None

    def load(self) -> None:
        if self._engine is not None:
            return

        if not self.model_path.is_file():
            raise FileNotFoundError(f"Kokoro ONNX model not found: {self.model_path}")
        if not self.voices_path.is_file():
            raise FileNotFoundError(f"Kokoro voices file not found: {self.voices_path}")

        try:
            from kokoro_onnx import Kokoro
        except ImportError as error:
            raise RuntimeError(
                'Kokoro ONNX is not installed. Run: python -m pip install -e ".[voice]"'
            ) from error

        self._engine = Kokoro(str(self.model_path), str(self.voices_path))

    @staticmethod
    def _float_samples_to_wav(
        samples: Any,
        sample_rate: int,
        *,
        max_duration_seconds: int = 180,
    ) -> bytes:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
            raise ValueError("Kokoro returned an invalid sample rate.")
        if not 8000 <= sample_rate <= 96000:
            raise ValueError("Kokoro returned an unsupported sample rate.")

        if hasattr(samples, "reshape") and hasattr(samples, "tolist"):
            flattened = samples.reshape(-1).tolist()
        elif hasattr(samples, "tolist"):
            flattened = samples.tolist()
        else:
            flattened = list(samples)

        if not flattened:
            raise ValueError("Kokoro returned empty audio.")
        if len(flattened) > sample_rate * max_duration_seconds:
            raise ValueError("Synthesized audio exceeds the 180-second safety limit.")

        pcm = array(
            "h",
            (
                max(
                    -32768,
                    min(
                        32767,
                        round(
                            (
                                float(value)
                                if math.isfinite(float(value))
                                else 0.0
                            )
                            * 32767.0
                        ),
                    ),
                )
                for value in flattened
            ),
        )

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(pcm.tobytes())
        return buffer.getvalue()

    def synthesize_wav(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        language: str = "en-us",
    ) -> bytes:
        """Synthesize one short response and return a PCM16 WAV payload."""
        self.load()

        if not isinstance(text, str) or not text.strip():
            raise ValueError("Speech text cannot be empty.")
        if len(text) > 12000:
            raise ValueError("Speech text exceeds the 12,000-character limit.")
        if not isinstance(speed, (int, float)) or isinstance(speed, bool):
            raise ValueError("Speech speed must be numeric.")
        if not math.isfinite(float(speed)) or not 0.5 <= float(speed) <= 2.0:
            raise ValueError("Speech speed must be between 0.5 and 2.0.")

        selected_voice = voice or self.default_voice
        if not isinstance(selected_voice, str) or not selected_voice.strip():
            raise ValueError("A Kokoro voice ID is required.")
        if not isinstance(language, str) or language not in {
            "en-us",
            "en-gb",
            "ja",
            "zh",
            "es",
            "fr-fr",
            "hi",
            "it",
            "pt-br",
        }:
            raise ValueError("Unsupported Kokoro language.")

        samples, sample_rate = self._engine.create(
            text.strip(),
            voice=selected_voice,
            speed=float(speed),
            lang=language,
        )
        return self._float_samples_to_wav(samples, int(sample_rate))

    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        language: str = "en-us",
    ):
        """Yield in-memory WAV chunks as Kokoro finishes each synthesis batch."""
        await asyncio.to_thread(self.load)

        if not isinstance(text, str) or not text.strip():
            raise ValueError("Speech text cannot be empty.")
        if len(text) > 12000:
            raise ValueError("Speech text exceeds the 12,000-character limit.")
        if not isinstance(speed, (int, float)) or isinstance(speed, bool):
            raise ValueError("Speech speed must be numeric.")
        if not math.isfinite(float(speed)) or not 0.5 <= float(speed) <= 2.0:
            raise ValueError("Speech speed must be between 0.5 and 2.0.")

        selected_voice = voice or self.default_voice
        if not isinstance(selected_voice, str) or not selected_voice.strip():
            raise ValueError("A Kokoro voice ID is required.")
        if not isinstance(language, str) or language not in {
            "en-us",
            "en-gb",
            "ja",
            "zh",
            "es",
            "fr-fr",
            "hi",
            "it",
            "pt-br",
        }:
            raise ValueError("Unsupported Kokoro language.")

        stream_factory = getattr(self._engine, "create_stream", None)
        if not callable(stream_factory):
            wav_data = await asyncio.to_thread(
                self.synthesize_wav,
                text,
                voice=selected_voice,
                speed=float(speed),
                language=language,
            )
            yield wav_data
            return

        async for samples, sample_rate in stream_factory(
            text.strip(),
            voice=selected_voice,
            speed=float(speed),
            lang=language,
        ):
            wav_data = await asyncio.to_thread(
                self._float_samples_to_wav,
                samples,
                int(sample_rate),
            )
            yield wav_data

    def close(self) -> None:
        self._engine = None
