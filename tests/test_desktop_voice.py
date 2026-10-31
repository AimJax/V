import unittest

from unittest.mock import AsyncMock

from v.desktop.service import (
    DesktopService,
    DesktopSnapshot,
    DesktopTurnResult,
)
from v.voice.whisper import TranscriptionResult


class FakeVoiceService:
    async def transcribe(self, _wav_data):
        return TranscriptionResult(
            text="Please help me test voice.",
            language="english",
            duration_seconds=2.0,
        )

    async def synthesize(self, _text):
        raise RuntimeError("Kokoro model is not installed.")

    async def close(self):
        return None


class DesktopVoiceTurnTests(unittest.IsolatedAsyncioTestCase):
    def _turn_result(self):
        snapshot = DesktopSnapshot(
            conversation=None,
            conversations=[],
            messages=[],
            model="gemma-4-e4b-it",
            network_mode="OFFLINE",
            semantic_memory_enabled=True,
        )
        return DesktopTurnResult(
            response="Voice pipeline response.",
            snapshot=snapshot,
        )

    async def test_voice_turn_uses_transcript_with_normal_chat_path(self):
        service = DesktopService()
        service.settings = {
            "voice": {
                "enabled": True,
                "speak_replies": False,
            }
        }
        service.voice_service = FakeVoiceService()
        service.send_message = AsyncMock(return_value=self._turn_result())
        on_token = lambda _token: None

        result = await service.send_voice_message(b"RIFFfake-wav", on_token)

        self.assertEqual(result.transcription, "Please help me test voice.")
        self.assertIsNone(result.audio_wav)
        self.assertIsNone(result.speech_error)
        service.send_message.assert_awaited_once_with(
            "Please help me test voice.",
            on_token,
        )

    async def test_tts_failure_does_not_discard_completed_text_response(self):
        service = DesktopService()
        service.settings = {
            "voice": {
                "enabled": True,
                "speak_replies": True,
            }
        }
        service.voice_service = FakeVoiceService()
        service.send_message = AsyncMock(return_value=self._turn_result())

        result = await service.send_voice_message(
            b"RIFFfake-wav",
            lambda _token: None,
        )

        self.assertEqual(result.turn.response, "Voice pipeline response.")
        self.assertIsNone(result.audio_wav)
        self.assertIn("Kokoro model is not installed", result.speech_error)


if __name__ == "__main__":
    unittest.main()
