import unittest

from unittest.mock import patch
from pathlib import Path

from support import temporary_directory

from v.conversations.store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.store = ConversationStore(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_retrieve_conversation(self):
        conversation = self.store.create_conversation("Test")

        found = self.store.get_conversation(conversation.id)

        self.assertIsNotNone(found)
        self.assertEqual(found.title, "Test")
        self.assertEqual(found.id, conversation.id)

    def test_latest_conversation(self):
        with patch(
            "v.conversations.store._timestamp",
            return_value="2026-10-31T10:00:00.000000+00:00",
        ):
            first = self.store.create_conversation("First")
            second = self.store.create_conversation("Second")

        latest = self.store.get_latest_conversation()

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(latest.id, second.id)

    def test_messages_survive_store_reinitialization(self):
        conversation = self.store.create_conversation()

        self.store.add_message(
            conversation.id,
            "user",
            "Hello V",
        )
        self.store.add_message(
            conversation.id,
            "assistant",
            "Hello. How are you?",
        )

        reopened_store = ConversationStore(self.database_path)
        messages = reopened_store.get_recent_messages(conversation.id)

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, "Hello V")
        self.assertEqual(messages[1].content, "Hello. How are you?")

    def test_first_user_message_sets_title(self):
        conversation = self.store.create_conversation()

        self.store.add_message(
            conversation.id,
            "user",
            "I want to talk about music.",
        )

        updated = self.store.get_conversation(conversation.id)

        self.assertEqual(updated.title, "I want to talk about music.")

    def test_historical_user_message_pages_are_ordered_and_bounded(self):
        first = self.store.create_conversation("First")
        second = self.store.create_conversation("Second")
        user_one = self.store.add_message(first.id, "user", "User message one.")
        self.store.add_message(first.id, "assistant", "Assistant reply.")
        user_two = self.store.add_message(second.id, "user", "User message two.")
        user_three = self.store.add_message(first.id, "user", "User message three.")

        self.assertEqual(
            self.store.max_user_message_id(),
            user_three,
        )
        self.assertEqual(
            self.store.count_user_messages(through_id=user_two),
            2,
        )
        page_one = self.store.list_user_messages(
            after_id=0,
            through_id=user_two,
            limit=1,
        )
        page_two = self.store.list_user_messages(
            after_id=page_one[-1].id,
            through_id=user_two,
            limit=5,
        )

        self.assertEqual([item.id for item in page_one], [user_one])
        self.assertEqual([item.id for item in page_two], [user_two])
        self.assertEqual(
            [item.content for item in page_one + page_two],
            ["User message one.", "User message two."],
        )
        self.assertEqual(
            self.store.list_user_messages(after_id=user_three, limit=5),
            [],
        )

    def test_message_insert_returns_permanent_message_id(self):
        conversation = self.store.create_conversation("IDs")
        message_id = self.store.add_message(
            conversation.id,
            "user",
            "Return the persistent ID.",
        )
        self.assertIsInstance(message_id, int)
        self.assertEqual(
            self.store.get_message_record(message_id).content,
            "Return the persistent ID.",
        )

    def test_surrounding_context_is_limited_to_same_conversation_and_excludes_target(self):
        conversation = self.store.create_conversation("Context")
        other = self.store.create_conversation("Other")

        before_id = self.store.add_message(
            conversation.id,
            "user",
            "Earlier user context.",
        )
        self.store.add_message(
            conversation.id,
            "assistant",
            "Assistant clarification.",
        )
        target_id = self.store.add_message(
            conversation.id,
            "user",
            "The actual source statement.",
        )
        self.store.add_message(
            conversation.id,
            "assistant",
            "Follow-up clarification.",
        )
        self.store.add_message(
            conversation.id,
            "user",
            "Later user context that is longer than the cap.",
        )
        self.store.add_message(
            other.id,
            "user",
            "Must never leak across conversations.",
        )

        context = self.store.get_surrounding_messages(
            target_id,
            before=1,
            after=1,
            max_chars_per_message=24,
        )

        self.assertEqual([item.id for item in context], [
            before_id + 1,
            target_id + 1,
        ])
        self.assertEqual(
            [item.role for item in context],
            ["assistant", "assistant"],
        )
        self.assertEqual(
            [item.content for item in context],
            ["Assistant clarification.", "Follow-up clarification."],
        )
        self.assertNotIn(
            "Must never leak across conversations",
            " ".join(item.content for item in context),
        )

    def test_surrounding_context_validates_bounds(self):
        conversation = self.store.create_conversation("Bounds")
        target_id = self.store.add_message(conversation.id, "user", "Target.")
        with self.assertRaises(ValueError):
            self.store.get_surrounding_messages(target_id, before=6)
        with self.assertRaises(ValueError):
            self.store.get_surrounding_messages(target_id, max_chars_per_message=0)

    def test_recent_message_limit(self):
        conversation = self.store.create_conversation()

        for index in range(5):
            self.store.add_message(
                conversation.id,
                "user",
                f"Message {index}",
            )

        messages = self.store.get_recent_messages(
            conversation.id,
            limit=2,
        )

        self.assertEqual(
            [message.content for message in messages],
            ["Message 3", "Message 4"],
        )

    def test_message_role_validation(self):
        conversation = self.store.create_conversation()

        with self.assertRaises(ValueError):
            self.store.add_message(
                conversation.id,
                "system",
                "This should not be stored.",
            )

    def test_delete_conversation_cascades_to_messages_and_preserves_other_chats(self):
        deleted = self.store.create_conversation("Delete me")
        retained = self.store.create_conversation("Keep me")
        self.store.add_message(deleted.id, "user", "This should be deleted.")
        self.store.add_message(retained.id, "user", "This should remain.")

        self.assertTrue(self.store.delete_conversation(deleted.id))
        self.assertIsNone(self.store.get_conversation(deleted.id))
        self.assertEqual(self.store.count_messages(deleted.id), 0)
        self.assertIsNotNone(self.store.get_conversation(retained.id))
        self.assertEqual(self.store.count_messages(retained.id), 1)
        self.assertFalse(self.store.delete_conversation(deleted.id))

    def test_conversation_listing(self):
        self.store.create_conversation("One")
        self.store.create_conversation("Two")

        conversations = self.store.list_conversations()

        self.assertEqual(len(conversations), 2)


if __name__ == "__main__":
    unittest.main()