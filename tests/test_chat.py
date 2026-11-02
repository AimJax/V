import unittest

from pathlib import Path

from support import temporary_directory

from v.chat import (
    _build_messages,
    build_memory_retrieval_query,
    _correct_memory,
    load_personality,
    trim_history,
)
from v.core.config import load_settings
from v.conversations.store import ConversationStore
from v.memory.store import MemoryStore
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

    def test_contextual_follow_up_uses_recent_dialogue_for_memory_query(self):
        recent_messages = [
            ChatMessage(
                role="user",
                content="I'm developing Project V as a local AI companion.",
            ),
            ChatMessage(
                role="assistant",
                content="V currently stores conversations and retrieves long-term memories.",
            ),
        ]

        query = build_memory_retrieval_query(
            "How does it remember things?",
            recent_messages,
        )

        self.assertIn("Project V", query)
        self.assertIn("long-term memories", query)
        self.assertIn("Current user message:", query)
        self.assertTrue(query.endswith("How does it remember things?"))

    def test_standalone_query_does_not_inherit_unrelated_dialogue(self):
        recent_messages = [
            ChatMessage(
                role="user",
                content="I'm developing Project V as a local AI companion.",
            ),
            ChatMessage(
                role="assistant",
                content="We discussed long-term memory.",
            ),
        ]

        query = build_memory_retrieval_query(
            "How do I cook rice?",
            recent_messages,
        )

        self.assertEqual(query, "How do I cook rice?")

    def test_short_referential_question_uses_context(self):
        recent_messages = [
            ChatMessage(role="assistant", content="The model is Gemma 4 E4B."),
        ]

        query = build_memory_retrieval_query("Is that fast?", recent_messages)

        self.assertIn("Gemma 4 E4B", query)

    def test_acknowledgement_does_not_import_context(self):
        recent_messages = [
            ChatMessage(role="assistant", content="We discussed Project V."),
        ]

        query = build_memory_retrieval_query("Exactly.", recent_messages)

        self.assertEqual(query, "Exactly.")

    def test_contextual_memory_query_respects_context_bounds(self):
        recent_messages = [
            ChatMessage(role="assistant", content="A" * 2500),
        ]

        query = build_memory_retrieval_query(
            "What about that?",
            recent_messages,
            max_context_characters=120,
        )

        self.assertIn("Current user message:", query)
        self.assertTrue(query.endswith("What about that?"))
        self.assertNotIn("A" * 121, query)

    def test_memory_context_is_injected_into_system_message(self):
        with temporary_directory() as temp:
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


    def test_memory_correction_command_updates_content(self):
        with temporary_directory() as temp:
            store = MemoryStore(Path(temp) / "memory.sqlite3")
            memory = store.create_memory(
                content="The user likes jazz.",
                memory_type="preference",
                source_conversation_id="conversation-1",
                source_message_id=12,
            )

            _correct_memory(
                store,
                f'/memory correct {memory.id} content "The user prefers shoegaze."',
            )

            corrected = store.get_memory(memory.id)

        self.assertEqual(corrected.content, "The user prefers shoegaze.")
        self.assertEqual(corrected.source_conversation_id, "conversation-1")
        self.assertEqual(corrected.source_message_id, 12)
        self.assertEqual(corrected.created_at, memory.created_at)

    def test_memory_correction_can_clear_optional_evidence(self):
        with temporary_directory() as temp:
            store = MemoryStore(Path(temp) / "memory.sqlite3")
            memory = store.create_memory(
                content="A preference.",
                evidence="Original source text.",
            )

            _correct_memory(
                store,
                f"/memory correct {memory.id} evidence --clear",
            )

            corrected = store.get_memory(memory.id)

        self.assertIsNone(corrected.evidence)

    def test_no_memory_context_preserves_personality(self):
        with temporary_directory() as temp:
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