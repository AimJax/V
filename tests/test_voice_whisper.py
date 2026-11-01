import tempfile
import unittest

from pathlib import Path
from unittest.mock import AsyncMock

from v.voice.whisper import (
    WhisperServer,
    WhisperServerConfig,
    build_whisper_server_command,
)


class WhisperCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.executable = root / "whisper-server.exe"
        self.model = root / "ggml-base.bin"
        self.vad = root / "ggml-silero-v6.2.0.bin"
        for path in (self.executable, self.model, self.vad):
            path.write_bytes(b"test")
        self.config = WhisperServerConfig(
            executable=self.executable,
            model_path=self.model,
            vad_model_path=self.vad,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_server_binds_to_loopback_and_enables_silero_vad(self):
        command = build_whisper_server_command(self.config, port=8178)
        self.assertIn("--host", command)
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--port") + 1], "8178")
        self.assertNotIn("--no-gpu", command)
        self.assertIn("--vad", command)
        self.assertEqual(
            command[command.index("--vad-model") + 1],
            str(self.vad),
        )
        self.assertEqual(
            command[command.index("--vad-threshold") + 1],
            "0.5",
        )

    def test_cuda_is_not_disabled_by_default(self):
        command = build_whisper_server_command(self.config, port=8178)
        self.assertNotIn("--no-gpu", command)

    def test_rejects_non_loopback_host(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            build_whisper_server_command(
                self.config,
                port=8178,
                host="0.0.0.0",
            )

    def test_rejects_missing_model_files(self):
        missing = WhisperServerConfig(
            executable=self.executable,
            model_path=self.model,
            vad_model_path=self.model.parent / "missing-vad.bin",
        )
        with self.assertRaisesRegex(FileNotFoundError, "Silero VAD model"):
            build_whisper_server_command(missing, port=8178)

    def test_rejects_invalid_port(self):
        with self.assertRaisesRegex(ValueError, "port"):
            build_whisper_server_command(self.config, port=70000)


class WhisperTranscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_wav_to_local_inference_and_parses_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "whisper-server.exe"
            model = root / "ggml-base.bin"
            vad = root / "ggml-silero.bin"
            for path in (executable, model, vad):
                path.write_bytes(b"test")

            class FakeProcess:
                returncode = None
                def poll(self):
                    return None

            class FakeResponse:
                status_code = 200
                def json(self):
                    return {
                        "text": " Hello from V. ",
                        "language": "english",
                        "duration": 1.25,
                    }

            class FakeClient:
                def __init__(self):
                    self.post = AsyncMock(return_value=FakeResponse())

            server = WhisperServer(
                WhisperServerConfig(executable, model, vad)
            )
            server.process = FakeProcess()
            server._client = FakeClient()

            result = await server.transcribe(
                b"RIFFfake-wav",
                language="en",
            )

            self.assertEqual(result.text, "Hello from V.")
            self.assertEqual(result.language, "english")
            self.assertEqual(result.duration_seconds, 1.25)

            args = server._client.post.call_args
            self.assertEqual(args.args[0], "/inference")
            self.assertEqual(args.kwargs["data"]["language"], "en")
            self.assertEqual(args.kwargs["data"]["response_format"], "json")
            self.assertEqual(
                args.kwargs["files"]["file"][2],
                "audio/wav",
            )

    async def test_rejects_non_200_server_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "whisper-server.exe"
            model = root / "ggml-base.bin"
            vad = root / "ggml-silero.bin"
            for path in (executable, model, vad):
                path.write_bytes(b"test")

            class FakeProcess:
                returncode = None
                def poll(self):
                    return None

            class FakeResponse:
                status_code = 500
                text = "model error"

            class FakeClient:
                post = AsyncMock(return_value=FakeResponse())

            server = WhisperServer(
                WhisperServerConfig(executable, model, vad)
            )
            server.process = FakeProcess()
            server._client = FakeClient()

            with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                await server.transcribe(b"RIFFfake-wav")

    async def test_refuses_transcription_when_server_is_stopped(self):
        server = WhisperServer(
            WhisperServerConfig(Path("server.exe"), Path("model.bin"), Path("vad.bin"))
        )
        with self.assertRaisesRegex(RuntimeError, "not running"):
            await server.transcribe(b"RIFFfake-wav")


if __name__ == "__main__":
    unittest.main()
