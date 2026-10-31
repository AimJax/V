import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt

from v.conversations.store import Conversation
from v.desktop.service import DesktopSnapshot
from v.desktop.window import DesktopWindow, MessageBubble
from v.providers.base import ChatMessage


class DesktopWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = DesktopWindow(auto_start=False)

    def tearDown(self):
        self.window.close()

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
