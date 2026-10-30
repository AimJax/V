import tempfile
import unittest

from pathlib import Path

from v.chat import (
    _build_messages,
    load_personality,
    trim_history,
)
from v.core.config import load_settings
from v.conversations.store import ConversationStore
from v.providers.base import ChatMessage


class ChatTests(unittest.TestCase):
    def test_personality_is_loaded(self):
        settings = load_settings()
        personality = load_personality(settings)

        self.assertIn("You are V", personality)
        self.assertGreater(len(personality), 50)

    def test_history_trimming_preserves_system_message(self):
        messages = [
            ChatMessage(role="system", content="Personality"),
            ChatMessage(role="user", content="First"),
            ChatMessage(role="assistant", content="Second"),
            ChatMessage(role="user", content="Third"),
            ChatMessage(role="assistant", content="Fourth"),
        ]

        trim_history(messages, 2)

        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].content, "Third")
        self.assertEqual(messages[2].content, "Fourth")

    def test_history_limit_must_be_valid(self):
        messages = [
            ChatMessage(role="system", content="Personality")
        ]

        with self.assertRaises(ValueError):
            trim_history(messages, 1)

    def test_memory_context_is_injected_into_system_message(self):
        with tempfile.TemporaryDirectory(dir=r"G:\V\tmp") as temp:
            store = ConversationStore(
                Path(temp) / "conversations.sqlite3"
            )
            conversation = store.create_conversation("Test")

            messages = _build_messages(
                "V personality",
                store,
                conversation,
                24,
                memory_context="Relevant user preference.",
            )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "system")
        self.assertIn("V personality", messages[0].content)
        self.assertIn("Relevant user preference.", messages[0].content)

    def test_no_memory_context_preserves_personality(self):
        with tempfile.TemporaryDirectory(dir=r"G:\V\tmp") as temp:
            store = ConversationStore(
                Path(temp) / "conversations.sqlite3"
            )
            conversation = store.create_conversation("Test")

            messages = _build_messages(
                "V personality",
                store,
                conversation,
                24,
            )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "V personality")


if __name__ == "__main__":
    unittest.main()