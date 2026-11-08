import gc
import os
import unittest

from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from PySide6.QtCore import QEvent, Qt
from unittest.mock import patch

from v.conversations.store import Conversation
from v.desktop.service import DesktopSnapshot
from v.desktop.window import DesktopWindow, MessageBubble
from v.interaction import InteractionEventKind, InteractionModality
from v.providers.base import ChatMessage


class DesktopWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.application.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        cls.application.quit()
        cls.application = None
        gc.collect()

    def setUp(self):
        self.window = DesktopWindow(auto_start=False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def _snapshot(self):
        conversation = Conversation(
            id="a" * 32,
            title="Local companion setup",
            created_at="2026-10-31T10:00:00+00:00",
            updated_at="2026-10-31T10:01:00+00:00",
        )
        return DesktopSnapshot(
            conversation=conversation,
            conversations=[conversation],
            messages=[
                ChatMessage(role="user", content="Keep this conversation local."),
                ChatMessage(role="assistant", content="The model runs locally."),
            ],
            model="gemma-4-e4b-it",
            network_mode="OFFLINE",
            semantic_memory_enabled=True,
        )

    def test_window_starts_disabled_until_local_runtime_is_ready(self):
        self.assertFalse(self.window.send_button.isEnabled())
        self.assertFalse(self.window.new_chat_button.isEnabled())

        self.window._apply_snapshot(self._snapshot())
        self.application.processEvents()

        self.assertTrue(self.window.send_button.isEnabled())
        self.assertTrue(self.window.new_chat_button.isEnabled())

    def test_snapshot_restores_session_and_chat_history(self):
        snapshot = self._snapshot()
        self.window._apply_snapshot(snapshot)
        self.application.processEvents()

        self.assertEqual(
            self.window.conversation_title.text(),
            "Local companion setup",
        )
        self.assertIn("gemma-4-e4b-it", self.window.model_label.text())
        self.assertIn("OFFLINE", self.window.connection_label.text())
        self.assertEqual(self.window.conversation_list.count(), 1)

        labels = [
            label.text()
            for label in self.window.findChildren(QLabel)
        ]
        self.assertIn("Keep this conversation local.", labels)
        self.assertIn("The model runs locally.", labels)

    def test_delete_chat_requires_confirmation_and_targets_selected_conversation(self):
        snapshot = self._snapshot()
        self.window._apply_snapshot(snapshot)
        self.application.processEvents()

        self.assertTrue(self.window.delete_chat_button.isEnabled())
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as confirm, patch.object(self.window.runtime, "delete_conversation") as delete:
            self.window._delete_conversation()

        confirm.assert_called_once()
        delete.assert_called_once_with(snapshot.conversation.id)

    def test_delete_chat_cancel_does_not_delete_conversation(self):
        snapshot = self._snapshot()
        self.window._apply_snapshot(snapshot)
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.No,
        ), patch.object(self.window.runtime, "delete_conversation") as delete:
            self.window._delete_conversation()
        delete.assert_not_called()

    def test_sidebar_elides_long_titles_without_horizontal_scrollbar(self):
        title = "How should you explain technical subjects to me?"
        conversation = Conversation(
            id="c" * 32,
            title=title,
            created_at="2026-10-31T10:00:00+00:00",
            updated_at="2026-10-31T10:01:00+00:00",
        )
        snapshot = DesktopSnapshot(
            conversation=conversation,
            conversations=[conversation],
            messages=[],
            model="gemma-4-e4b-it",
            network_mode="OFFLINE",
            semantic_memory_enabled=True,
        )

        self.window._apply_snapshot(snapshot)
        self.application.processEvents()

        item = self.window.conversation_list.item(0)
        self.assertEqual(item.text(), title)
        self.assertEqual(item.toolTip(), title)
        self.assertEqual(
            self.window.conversation_list.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(
            self.window.conversation_list.textElideMode(),
            Qt.TextElideMode.ElideRight,
        )

    def test_push_to_talk_is_disabled_by_default_and_does_not_open_devices(self):
        self.assertFalse(self.window.voice_button.isEnabled())
        snapshot = self._snapshot()
        self.window._apply_snapshot(snapshot)
        self.application.processEvents()

        self.assertFalse(self.window.voice_button.isEnabled())
        self.assertIsNotNone(self.window._voice_recorder)
        self.assertFalse(self.window._voice_recorder.is_recording)

    def test_push_to_talk_is_enabled_only_when_voice_is_configured(self):
        snapshot = self._snapshot()
        object.__setattr__(snapshot, "voice_enabled", True)
        object.__setattr__(
            snapshot,
            "voice_settings",
            {
                "enabled": True,
                "input_device_id": "",
                "max_utterance_seconds": 30,
                "vad_min_speech_duration_ms": 250,
            },
        )
        self.window._apply_snapshot(snapshot)
        self.application.processEvents()

        self.assertTrue(self.window.voice_button.isEnabled())
        self.assertFalse(self.window._voice_recorder.is_recording)

    def test_attach_image_sends_selected_path_to_local_runtime(self):
        snapshot = self._snapshot()
        object.__setattr__(snapshot, "vision_settings", {"model": "gemma-chat"})
        self.window._apply_snapshot(snapshot)

        with patch(
            "v.desktop.window.QFileDialog.getOpenFileName",
            return_value=("G:/V/test-image.png", "Images (*.png)"),
        ), patch.object(self.window, "_stop_speech") as stop, patch.object(
            self.window.runtime, "send_image_turn"
        ) as send_image:
            self.window._attach_image()

        stop.assert_called_once_with()
        send_image.assert_called_once()
        self.assertEqual(send_image.call_args.args[0], "G:/V/test-image.png")
        self.assertIn("analyze the image", send_image.call_args.args[1].casefold())
        self.assertTrue(self.window._busy)

    def test_camera_sensor_state_is_recorded_with_camera_provenance(self):
        snapshot = self._snapshot()
        self.window._apply_snapshot(snapshot)

        with patch.object(self.window.runtime, "record_interaction_event") as record:
            self.window._on_camera_state_changed(True)

        event = record.call_args.args[0]
        self.assertEqual(event.kind, InteractionEventKind.SENSOR_STATE_CHANGED)
        self.assertEqual(event.modality, InteractionModality.CAMERA)
        self.assertEqual(event.activation_context, "user_camera_capture")
        self.assertEqual(event.content, "camera active")
        self.assertEqual(event.metadata["sensor"], "camera")

    def test_camera_snapshot_button_hands_one_frame_to_runtime(self):
        snapshot = self._snapshot()
        object.__setattr__(snapshot, "vision_settings", {"model": "gemma-chat"})
        self.window._apply_snapshot(snapshot)
        image_data = b"\xff\xd8camera-frame"
        captured_at = datetime.now(timezone.utc)

        with patch.object(self.window, "_stop_speech"), patch.object(
            self.window.runtime, "send_camera_turn"
        ) as send_camera:
            self.window._send_camera_image(image_data, captured_at)

        send_camera.assert_called_once()
        self.assertEqual(send_camera.call_args.args[0], image_data)
        self.assertEqual(send_camera.call_args.args[2], captured_at)
        self.assertIn("camera snapshot", send_camera.call_args.args[1].casefold())
        self.assertTrue(self.window._busy)

    def test_image_attachment_is_enabled_only_when_vision_is_configured(self):
        snapshot = self._snapshot()
        object.__setattr__(snapshot, "vision_settings", {"model": "local-chat-model"})

        self.window._apply_snapshot(snapshot)
        self.application.processEvents()

        self.assertTrue(self.window.attach_image_button.isEnabled())
        self.assertTrue(self.window.camera_button.isEnabled())

    def test_stop_speaking_button_interrupts_runtime_and_disables_itself(self):
        class FakePlayer:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

            def close(self):
                return None

        self.window._speech_player = FakePlayer()
        self.window.stop_speech_button.setEnabled(True)

        with patch.object(self.window.runtime, "interrupt_speech") as interrupt:
            self.window._stop_speech()

        self.assertTrue(self.window._speech_player.stopped)
        self.assertFalse(self.window.stop_speech_button.isEnabled())
        interrupt.assert_called_once_with()

    def test_stale_speech_chunk_is_discarded_after_interruption(self):
        self.window.runtime._speech_generation = 3

        self.window._enqueue_speech_audio((2, b"RIFFstale-audio"))

        self.assertIsNone(self.window._speech_player)
        self.assertFalse(self.window.stop_speech_button.isEnabled())

    def test_speech_finished_disables_stop_control(self):
        self.window.stop_speech_button.setEnabled(True)

        self.window._on_speech_finished()

        self.assertFalse(self.window.stop_speech_button.isEnabled())

    def test_settings_button_is_enabled_only_after_runtime_ready(self):
        self.assertFalse(self.window.settings_button.isEnabled())
        self.window._apply_snapshot(self._snapshot())
        self.application.processEvents()
        self.assertTrue(self.window.settings_button.isEnabled())

    def test_message_content_is_rendered_as_plain_text(self):
        bubble = MessageBubble("V", "<b>not markup</b>")
        self.assertEqual(
            bubble.content_label.textFormat(),
            Qt.TextFormat.PlainText,
        )
        self.assertEqual(bubble.content_label.text(), "<b>not markup</b>")

    def test_new_snapshot_replaces_visible_history(self):
        first = self._snapshot()
        self.window._apply_snapshot(first)
        self.application.processEvents()

        other = Conversation(
            id="b" * 32,
            title="Another session",
            created_at="2026-10-31T10:02:00+00:00",
            updated_at="2026-10-31T10:03:00+00:00",
        )
        second = DesktopSnapshot(
            conversation=other,
            conversations=[other, first.conversation],
            messages=[ChatMessage(role="user", content="A separate session.")],
            model="gemma-4-e4b-it",
            network_mode="OFFLINE",
            semantic_memory_enabled=False,
        )
        self.window._apply_snapshot(second)
        self.application.processEvents()

        labels = [
            label.text()
            for label in self.window.findChildren(QLabel)
        ]
        self.assertEqual(self.window.conversation_title.text(), "Another session")
        self.assertIn("A separate session.", labels)
        self.assertNotIn("Keep this conversation local.", labels)


if __name__ == "__main__":
    unittest.main()
