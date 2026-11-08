import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PySide6.QtGui import QImage

from v.conversations.store import Conversation
from v.desktop.service import DesktopService, DesktopSnapshot, DesktopTurnResult


class FakeVisionProvider:
    def __init__(self):
        self.calls = []

    async def analyze(self, image_data, *, mime_type, prompt):
        self.calls.append((image_data, mime_type, prompt))
        return "A blue ceramic mug on a wooden desk."


class DesktopVisionTurnTests(unittest.IsolatedAsyncioTestCase):
    def _turn_result(self, conversation):
        snapshot = DesktopSnapshot(
            conversation=conversation,
            conversations=[conversation],
            messages=[],
            model="local-vision-model",
            network_mode="OFFLINE",
            semantic_memory_enabled=False,
        )
        return DesktopTurnResult(
            response="It appears to be a blue mug.",
            snapshot=snapshot,
        )

    def _write_image(self, path: Path):
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(0x336699)
        self.assertTrue(image.save(str(path), "PNG"))

    async def test_uploaded_image_is_transient_and_enters_shared_chat_pipeline(self):
        conversation = Conversation(
            id="a" * 32,
            title="Image test",
            created_at="2026-11-08T00:00:00+00:00",
            updated_at="2026-11-08T00:00:00+00:00",
        )
        service = DesktopService()
        service.settings = {"vision": {"model": "local-vision-model"}}
        service.model = "local-vision-model"
        service.available_models = ["local-vision-model"]
        service.provider = SimpleNamespace(base_url="http://127.0.0.1:1234/v1")
        service.conversation = conversation
        service.vision_provider = FakeVisionProvider()
        service.cancel_background_model_work = AsyncMock()
        service.send_message = AsyncMock(
            return_value=self._turn_result(conversation)
        )
        events = []
        callback = events.append

        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "user-image.png"
            self._write_image(image_path)
            original = image_path.read_bytes()
            result = await service.send_image_message(
                str(image_path),
                "What is in this image?",
                lambda _token: None,
                on_interaction_event=callback,
            )

            self.assertEqual(image_path.read_bytes(), original)

        self.assertEqual(result.response, "It appears to be a blue mug.")
        self.assertEqual(len(service.vision_provider.calls), 1)
        image_bytes, mime_type, prompt = service.vision_provider.calls[0]
        self.assertTrue(image_bytes.startswith(b"\xff\xd8"))
        self.assertEqual(mime_type, "image/jpeg")
        self.assertEqual(prompt, "What is in this image?")

        call = service.send_message.await_args
        self.assertEqual(call.args[0], "What is in this image?")
        user_event = call.kwargs["interaction_event"]
        observation_event = call.kwargs["additional_events"][0]
        self.assertEqual(user_event.kind.value, "user_message")
        self.assertEqual(user_event.modality.value, "image")
        self.assertEqual(user_event.activation_context, "user_upload")
        self.assertEqual(user_event.conversation_id, conversation.id)
        self.assertEqual(observation_event.kind.value, "image_observation")
        self.assertEqual(observation_event.activation_context, "local_vision_model")
        self.assertEqual(observation_event.source_ref, user_event.event_id)
        self.assertEqual(observation_event.content, "A blue ceramic mug on a wooden desk.")
        self.assertIs(call.kwargs["on_interaction_event"], callback)
        self.assertIn("UNTRUSTED VISUAL OBSERVATION", call.kwargs["additional_system_context"])
        self.assertNotIn(str(image_path), call.kwargs["additional_system_context"])

    async def test_image_analysis_requires_selected_chat_model_to_protect_vram(self):
        service = DesktopService()
        service.settings = {"vision": {"model": "separate-vision-model"}}
        service.model = "chat-model"
        service.available_models = ["chat-model", "separate-vision-model"]

        with self.assertRaisesRegex(RuntimeError, "same as V's chat model"):
            await service.send_image_message(
                "does-not-need-to-exist.png",
                "Describe it",
                lambda _token: None,
            )


if __name__ == "__main__":
    unittest.main()
