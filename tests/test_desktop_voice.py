import unittest

from unittest.mock import AsyncMock

from v.conversations.store import Conversation
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


class FakeChatProvider:
    async def stream_chat(self, *_args, **_kwargs):
        yield "Voice pipeline response."


class FakeConversationStore:
    def __init__(self, conversation):
        self.conversation = conversation
        self.saved = []

    def get_recent_messages(self, *_args):
        return []

    def add_message(self, _conversation_id, role, content):
        self.saved.append((role, content))
        return len(self.saved)

    def get_conversation(self, _conversation_id):
        return self.conversation

    def list_conversations(self, limit=50):
        return [self.conversation]


class DesktopVoiceTurnTests(unittest.IsolatedAsyncioTestCase):
    def _turn_result(self):
        conversation = Conversation(
            id="a" * 32,
            title="Voice test",
            created_at="2026-11-01T00:00:00+00:00",
            updated_at="2026-11-01T00:00:00+00:00",
        )
        snapshot = DesktopSnapshot(
            conversation=conversation,
            conversations=[conversation],
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

    async def test_speech_starts_queueing_before_chat_generation_finishes(self):
        import asyncio

        release_generation = asyncio.Event()

        class PausingChatProvider:
            async def stream_chat(self, *_args, **_kwargs):
                yield "First sentence."
                yield " "
                await release_generation.wait()
                yield "Second sentence."

        service = DesktopService()
        service.settings = {
            "memory": {"retrieval_enabled": False},
            "voice": {
                "enabled": True,
                "speak_replies": True,
            },
        }
        service.provider = PausingChatProvider()
        service.conversation = self._turn_result().snapshot.conversation
        service.conversation_store = FakeConversationStore(service.conversation)
        service.personality = "You are V."
        service.started = True
        service._speech_queue = asyncio.Queue()

        audio_chunks = []
        speech_errors = []
        task = asyncio.create_task(
            service.send_message(
                "Please respond.",
                lambda _token: None,
                audio_chunks.append,
                speech_errors.append,
            )
        )

        first = await asyncio.wait_for(service._speech_queue.get(), timeout=1)
        self.assertEqual(first[1], "First sentence.")
        self.assertFalse(task.done())

        release_generation.set()
        result = await task

        self.assertEqual(result.response, "First sentence. Second sentence.")
        self.assertIsNone(result.audio_wav)
        self.assertIsNone(result.speech_error)
        second = service._speech_queue.get_nowait()
        self.assertEqual(second[1], "Second sentence.")
        self.assertEqual(audio_chunks, [])
        self.assertEqual(speech_errors, [])

    async def test_voice_turn_forwards_speech_callbacks_to_chat_path(self):
        service = DesktopService()
        service.settings = {
            "voice": {
                "enabled": True,
                "speak_replies": True,
            }
        }
        service.voice_service = FakeVoiceService()
        service.send_message = AsyncMock(return_value=self._turn_result())
        on_token = lambda _token: None
        on_audio = lambda _audio: None
        on_error = lambda _error: None

        result = await service.send_voice_message(
            b"RIFFfake-wav",
            on_token,
            on_audio,
            on_error,
        )

        self.assertEqual(result.transcription, "Please help me test voice.")
        service.send_message.assert_awaited_once_with(
            "Please help me test voice.",
            on_token,
            on_audio,
            on_error,
        )


if __name__ == "__main__":
    unittest.main()
