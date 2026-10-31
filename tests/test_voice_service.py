import asyncio
import tempfile
import unittest

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from v.voice.service import LocalVoiceService
from v.voice.whisper import TranscriptionResult


class LocalVoiceServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = {
            "whisper_server_path": "apps/whisper/whisper-server.exe",
            "whisper_model_path": "models/whisper/ggml-base.bin",
            "silero_vad_model_path": "models/whisper/ggml-silero.bin",
            "kokoro_model_path": "models/kokoro/kokoro.onnx",
            "kokoro_voices_path": "models/kokoro/voices.bin",
            "kokoro_voice": "af_heart",
            "tts_speed": 1.0,
            "enabled": True,
            "speak_replies": True,
            "stt_language": "en",
        }
        for relative in (
            "apps/whisper/whisper-server.exe",
            "models/whisper/ggml-base.bin",
            "models/whisper/ggml-silero.bin",
            "models/kokoro/kokoro.onnx",
            "models/kokoro/voices.bin",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test")

    def tearDown(self):
        self.temp.cleanup()

    async def test_disabled_voice_fails_without_loading_any_engine(self):
        service = LocalVoiceService(
            {"voice": {"enabled": False}},
            root=self.root,
        )

        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await service.transcribe(b"RIFFfake-wav")

        self.assertIsNone(service.server)

    async def test_transcribe_starts_local_whisper_and_returns_text(self):
        fake_server = Mock()
        fake_server.start = AsyncMock(return_value="http://127.0.0.1:18000")
        fake_server.transcribe = AsyncMock(
            return_value=TranscriptionResult(
                text="Hello V.",
                language="english",
                duration_seconds=1.2,
            )
        )
        service = LocalVoiceService(
            {"voice": self.assets},
            root=self.root,
        )

        with patch("v.voice.service.WhisperServer", return_value=fake_server):
            result = await service.transcribe(b"RIFFfake-wav")

        self.assertEqual(result.text, "Hello V.")
        fake_server.start.assert_awaited_once()
        fake_server.transcribe.assert_awaited_once_with(
            b"RIFFfake-wav",
            language="en",
        )

    async def test_synthesize_runs_kokoro_off_the_async_event_loop(self):
        fake_engine = Mock()
        fake_engine.synthesize_wav.return_value = b"RIFFvoice"
        service = LocalVoiceService(
            {"voice": self.assets},
            root=self.root,
        )

        with patch("v.voice.service.KokoroSpeechEngine", return_value=fake_engine):
            result = await service.synthesize("Hello V.")

        self.assertEqual(result, b"RIFFvoice")
        fake_engine.synthesize_wav.assert_called_once_with(
            "Hello V.",
            voice="af_heart",
            speed=1.0,
            language="en-us",
        )

    async def test_rejects_voice_asset_path_outside_project(self):
        settings = {
            "voice": {
                **self.assets,
                "whisper_server_path": "../outside/whisper-server.exe",
            }
        }
        service = LocalVoiceService(settings, root=self.root)

        with self.assertRaisesRegex(ValueError, "inside the V project"):
            service._whisper()


if __name__ == "__main__":
    unittest.main()
