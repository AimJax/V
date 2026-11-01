import asyncio
import importlib
import io
import sys
import tempfile
import types
import unittest
import wave

from pathlib import Path
from unittest.mock import Mock, patch

from v.voice.kokoro import KokoroSpeechEngine


class KokoroSpeechEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.model = root / "kokoro-v1.0.onnx"
        self.voices = root / "voices-v1.0.bin"
        self.model.write_bytes(b"model")
        self.voices.write_bytes(b"voices")

    def tearDown(self):
        self.temp.cleanup()

    def _mock_kokoro_module(self, samples=None, sample_rate=24000):
        instance = Mock()
        instance.create.return_value = (
            samples if samples is not None else [0.0, 0.5, -0.5, 1.0],
            sample_rate,
        )
        module = types.ModuleType("kokoro_onnx")
        module.Kokoro = Mock(return_value=instance)
        return module, instance

    def test_synthesizes_pcm16_wav_in_memory(self):
        module, instance = self._mock_kokoro_module()
        engine = KokoroSpeechEngine(self.model, self.voices)

        with patch.dict(sys.modules, {"kokoro_onnx": module}):
            wav_data = engine.synthesize_wav(
                "Hello from V.",
                voice="af_heart",
                speed=1.0,
                language="en-us",
            )

        self.assertTrue(wav_data.startswith(b"RIFF"))
        with wave.open(io.BytesIO(wav_data), "rb") as reader:
            self.assertEqual(reader.getnchannels(), 1)
            self.assertEqual(reader.getsampwidth(), 2)
            self.assertEqual(reader.getframerate(), 24000)
            self.assertEqual(reader.getnframes(), 4)

        instance.create.assert_called_once_with(
            "Hello from V.",
            voice="af_heart",
            speed=1.0,
            lang="en-us",
        )

    def test_loads_model_only_once(self):
        module, _instance = self._mock_kokoro_module()
        engine = KokoroSpeechEngine(self.model, self.voices)
        with patch.dict(sys.modules, {"kokoro_onnx": module}):
            engine.load()
            engine.load()
        module.Kokoro.assert_called_once_with(
            str(self.model),
            str(self.voices),
        )

    def test_synthesize_stream_yields_wav_chunks(self):
        engine = KokoroSpeechEngine(self.model, self.voices)
        instance = Mock()

        async def create_stream(text, *, voice, speed, lang):
            self.assertEqual(text, "Hello there.")
            self.assertEqual(voice, "af_heart")
            self.assertEqual(speed, 1.0)
            self.assertEqual(lang, "en-us")
            yield [0.0, 0.5], 24000
            yield [-0.5, 0.0], 24000

        instance.create_stream = create_stream
        engine._engine = instance

        async def collect():
            return [
                chunk
                async for chunk in engine.synthesize_stream("Hello there.")
            ]

        chunks = asyncio.run(collect())
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(chunk.startswith(b"RIFF") for chunk in chunks))

    def test_missing_model_is_reported_before_import(self):
        engine = KokoroSpeechEngine(
            self.model.parent / "missing.onnx",
            self.voices,
        )
        with patch.dict(sys.modules, {"kokoro_onnx": Mock()}):
            with self.assertRaisesRegex(FileNotFoundError, "ONNX model"):
                engine.load()

    def test_rejects_empty_text(self):
        module, _instance = self._mock_kokoro_module()
        engine = KokoroSpeechEngine(self.model, self.voices)
        with patch.dict(sys.modules, {"kokoro_onnx": module}):
            with self.assertRaisesRegex(ValueError, "cannot be empty"):
                engine.synthesize_wav("   ")

    def test_rejects_invalid_speed(self):
        module, _instance = self._mock_kokoro_module()
        engine = KokoroSpeechEngine(self.model, self.voices)
        with patch.dict(sys.modules, {"kokoro_onnx": module}):
            with self.assertRaisesRegex(ValueError, "between 0.5 and 1.5"):
                engine.synthesize_wav("Hello", speed=1.6)

    def test_rejects_unsupported_language(self):
        module, _instance = self._mock_kokoro_module()
        engine = KokoroSpeechEngine(self.model, self.voices)
        with patch.dict(sys.modules, {"kokoro_onnx": module}):
            with self.assertRaisesRegex(ValueError, "Unsupported Kokoro language"):
                engine.synthesize_wav("Hello", language="id")

    def test_rejects_empty_waveform(self):
        module, _instance = self._mock_kokoro_module(samples=[])
        engine = KokoroSpeechEngine(self.model, self.voices)
        with patch.dict(sys.modules, {"kokoro_onnx": module}):
            with self.assertRaisesRegex(ValueError, "empty audio"):
                engine.synthesize_wav("Hello")


if __name__ == "__main__":
    unittest.main()
