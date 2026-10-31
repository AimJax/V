"""On-demand local Whisper STT and Kokoro ONNX TTS orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from v.core.config import project_root
from v.voice.kokoro import KokoroSpeechEngine
from v.voice.whisper import (
    TranscriptionResult,
    WhisperServer,
    WhisperServerConfig,
)


def _project_path(root: Path, value: str, label: str) -> Path:
    candidate = Path(value).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must remain inside the V project directory.")
    return resolved


class LocalVoiceService:
    """Lazily start local speech engines; do not access microphone devices here."""

    def __init__(
        self,
        settings: dict[str, Any],
        *,
        root: Path | None = None,
    ) -> None:
        self.settings = dict(settings)
        self.root = (root or project_root()).resolve()
        self.config = self.settings.get("voice", {})
        if not isinstance(self.config, dict):
            raise ValueError("Voice configuration must be a table.")

        self.server: WhisperServer | None = None
        self.tts: KokoroSpeechEngine | None = None

    def _enabled(self) -> None:
        if not self.config.get("enabled", False):
            raise RuntimeError(
                "Local voice interaction is disabled. Enable it in V Settings and restart."
            )

    def _whisper(self) -> WhisperServer:
        if self.server is not None:
            return self.server

        voice = self.config
        executable = _project_path(
            self.root,
            str(voice.get("whisper_server_path", "")),
            "Whisper server path",
        )
        model = _project_path(
            self.root,
            str(voice.get("whisper_model_path", "")),
            "Whisper model path",
        )
        vad = _project_path(
            self.root,
            str(voice.get("silero_vad_model_path", "")),
            "Silero VAD model path",
        )

        self.server = WhisperServer(
            WhisperServerConfig(
                executable=executable,
                model_path=model,
                vad_model_path=vad,
                threads=int(voice.get("stt_threads", 4)),
                language=str(voice.get("stt_language", "auto")),
                vad_threshold=float(voice.get("vad_threshold", 0.50)),
                vad_min_speech_duration_ms=int(
                    voice.get("vad_min_speech_duration_ms", 250)
                ),
                vad_min_silence_duration_ms=int(
                    voice.get("vad_silence_duration_ms", 700)
                ),
                max_speech_duration_seconds=int(
                    voice.get("max_utterance_seconds", 30)
                ),
            ),
            log_path=self.root / "logs" / "voice" / "whisper-server.log",
        )
        return self.server

    def _kokoro(self) -> KokoroSpeechEngine:
        if self.tts is not None:
            return self.tts

        voice = self.config
        model = _project_path(
            self.root,
            str(voice.get("kokoro_model_path", "")),
            "Kokoro model path",
        )
        voices = _project_path(
            self.root,
            str(voice.get("kokoro_voices_path", "")),
            "Kokoro voices path",
        )
        self.tts = KokoroSpeechEngine(
            model,
            voices,
            default_voice=str(voice.get("kokoro_voice", "af_heart")),
        )
        return self.tts

    async def transcribe(self, wav_data: bytes) -> TranscriptionResult:
        self._enabled()
        server = self._whisper()
        await server.start()
        return await server.transcribe(
            wav_data,
            language=str(self.config.get("stt_language", "auto")),
        )

    async def synthesize(self, text: str) -> bytes:
        self._enabled()
        engine = self._kokoro()
        return await asyncio.to_thread(
            engine.synthesize_wav,
            text,
            voice=str(self.config.get("kokoro_voice", "af_heart")),
            speed=float(self.config.get("tts_speed", 1.0)),
            language="en-us",
        )

    async def close(self) -> None:
        if self.server is not None:
            await self.server.close()
            self.server = None
        if self.tts is not None:
            self.tts.close()
            self.tts = None
