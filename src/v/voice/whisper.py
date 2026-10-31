"""Pinned local whisper.cpp server management and transcription client."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import subprocess
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class WhisperServerConfig:
    executable: Path
    model_path: Path
    vad_model_path: Path
    threads: int = 4
    language: str = "auto"
    vad_threshold: float = 0.50
    vad_min_speech_duration_ms: int = 250
    vad_min_silence_duration_ms: int = 700
    max_speech_duration_seconds: int = 30
    startup_timeout_seconds: float = 60.0
    request_timeout_seconds: float = 120.0


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration_seconds: float | None


def _validate_loopback_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("Whisper server host must be a literal loopback IP address.") from error
    if not address.is_loopback:
        raise ValueError("Whisper server may only bind to a loopback address.")
    return str(address)


def build_whisper_server_command(
    config: WhisperServerConfig,
    *,
    port: int,
    host: str = "127.0.0.1",
) -> list[str]:
    """Build arguments for a CPU-only server bound exclusively to loopback."""
    host = _validate_loopback_host(host)

    if not 1 <= port <= 65535:
        raise ValueError("Whisper server port must be between 1 and 65535.")
    if not 1 <= config.threads <= 8:
        raise ValueError("Whisper thread count must be between 1 and 8.")
    if config.language not in {"auto", "en", "id"}:
        raise ValueError("Whisper language must be auto, en, or id.")
    if not 0.1 <= config.vad_threshold <= 0.95:
        raise ValueError("VAD threshold must be between 0.1 and 0.95.")
    if not 50 <= config.vad_min_speech_duration_ms <= 2000:
        raise ValueError("VAD minimum speech duration is out of range.")
    if not 100 <= config.vad_min_silence_duration_ms <= 3000:
        raise ValueError("VAD minimum silence duration is out of range.")
    if not 5 <= config.max_speech_duration_seconds <= 120:
        raise ValueError("Maximum speech duration is out of range.")

    for path, label in (
        (config.executable, "Whisper server executable"),
        (config.model_path, "Whisper model"),
        (config.vad_model_path, "Silero VAD model"),
    ):
        if not Path(path).is_file():
            raise FileNotFoundError(f"{label} not found: {path}")

    return [
        str(config.executable),
        "--host", host,
        "--port", str(port),
        "--model", str(config.model_path),
        "--threads", str(config.threads),
        "--language", config.language,
        "--no-gpu",
        "--vad",
        "--vad-model", str(config.vad_model_path),
        "--vad-threshold", str(config.vad_threshold),
        "--vad-min-speech-duration-ms", str(config.vad_min_speech_duration_ms),
        "--vad-min-silence-duration-ms", str(config.vad_min_silence_duration_ms),
        "--vad-max-speech-duration-s", str(config.max_speech_duration_seconds),
    ]


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class WhisperServer:
    """Own one private whisper.cpp process and its loopback HTTP client."""

    def __init__(
        self,
        config: WhisperServerConfig,
        *,
        log_path: Path | None = None,
    ) -> None:
        self.config = config
        self.log_path = log_path
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self._client: httpx.AsyncClient | None = None
        self._log_handle = None

    @property
    def base_url(self) -> str | None:
        if self.port is None:
            return None
        return f"http://127.0.0.1:{self.port}"

    def _open_log(self):
        if self.log_path is None:
            return subprocess.DEVNULL
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("ab")
        return self._log_handle

    async def start(self) -> str:
        if self.process is not None and self.process.poll() is None:
            return str(self.base_url)

        self.port = _reserve_loopback_port()
        command = build_whisper_server_command(
            self.config,
            port=self.port,
            host="127.0.0.1",
        )
        stdout_target = self._open_log()

        try:
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(
                command,
                cwd=str(self.config.executable.parent),
                stdin=subprocess.DEVNULL,
                stdout=stdout_target,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=creation_flags,
            )
            self._client = httpx.AsyncClient(
                base_url=str(self.base_url),
                timeout=httpx.Timeout(self.config.request_timeout_seconds),
                trust_env=False,
                follow_redirects=False,
            )

            deadline = time.monotonic() + self.config.startup_timeout_seconds
            last_error = "server did not respond"
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        f"whisper-server exited during startup with code {self.process.returncode}. "
                        "Inspect the local voice log."
                    )
                try:
                    response = await self._client.get("/")
                    if response.status_code < 500:
                        return str(self.base_url)
                    last_error = f"HTTP {response.status_code}"
                except httpx.HTTPError as error:
                    last_error = str(error)
                await asyncio.sleep(0.25)

            raise TimeoutError(
                f"whisper-server did not become ready within "
                f"{self.config.startup_timeout_seconds:g} seconds: {last_error}"
            )
        except Exception:
            await self.close()
            raise

    async def transcribe(
        self,
        wav_data: bytes,
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Whisper server is not running.")
        if self._client is None:
            raise RuntimeError("Whisper client is not initialized.")
        if not isinstance(wav_data, bytes) or not wav_data:
            raise ValueError("Audio payload is empty.")
        if len(wav_data) > 24 * 1024 * 1024:
            raise ValueError("Audio payload exceeds the 24 MiB limit.")

        selected_language = language or self.config.language
        if selected_language not in {"auto", "en", "id"}:
            raise ValueError("Whisper language must be auto, en, or id.")

        response = await self._client.post(
            "/inference",
            data={
                "response_format": "json",
                "temperature": "0.0",
                "temperature_inc": "0.0",
                "language": selected_language,
                "no_timestamps": "true",
                "no_language_probabilities": "true",
            },
            files={
                "file": ("utterance.wav", wav_data, "audio/wav"),
            },
        )

        if response.status_code != 200:
            detail = response.text[:1000]
            raise RuntimeError(
                f"Whisper transcription failed (HTTP {response.status_code}): {detail}"
            )

        try:
            payload: Any = response.json()
        except ValueError as error:
            raise RuntimeError("Whisper returned invalid JSON.") from error

        if not isinstance(payload, dict):
            raise RuntimeError("Whisper returned an unexpected response format.")

        text = payload.get("text")
        if not isinstance(text, str):
            raise RuntimeError("Whisper response did not contain transcription text.")

        return TranscriptionResult(
            text=text.strip(),
            language=(
                payload.get("language")
                if isinstance(payload.get("language"), str)
                else None
            ),
            duration_seconds=(
                float(payload["duration"])
                if isinstance(payload.get("duration"), (int, float))
                else None
            ),
        )

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)

        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
        self.port = None
