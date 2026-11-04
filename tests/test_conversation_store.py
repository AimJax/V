import tempfile
import unittest
from pathlib import Path

from v.conversations.store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
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
        self.store.create_conversation("First")
        second = self.store.create_conversation("Second")
        latest = self.store.get_latest_conversation()
        self.assertEqual(latest.id, second.id)

    def test_messages_survive_store_reinitialization(self):
        conversation = self.store.create_conversation()
        user_message_id = self.store.add_message(conversation.id, "user", "Hello V")
        self.assertIsInstance(user_message_id, int)
        self.assertEqual(self.store.get_message_record(user_message_id).content, "Hello V")
        self.store.add_message(conversation.id, "assistant", "Hello. How are you?")
        reopened_store = ConversationStore(self.database_path)
        messages = reopened_store.get_recent_messages(conversation.id)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, "Hello V")
        self.assertEqual(messages[1].content, "Hello. How are you?")

    def test_first_user_message_sets_title(self):
        conversation = self.store.create_conversation()
        self.store.add_message(conversation.id, "user", "I want to talk about music.")
        updated = self.store.get_conversation(conversation.id)
        self.assertEqual(updated.title, "I want to talk about music.")

    def test_recent_message_limit(self):
        conversation = self.store.create_conversation()
        for index in range(5):
            self.store.add_message(conversation.id, "user", f"Message {index}")
        messages = self.store.get_recent_messages(conversation.id, limit=2)
        self.assertEqual([message.content for message in messages], ["Message 3", "Message 4"])

    def test_message_role_validation(self):
        conversation = self.store.create_conversation()
        with self.assertRaises(ValueError):
            self.store.add_message(conversation.id, "system", "This should not be stored.")

    def test_conversation_listing(self):
        self.store.create_conversation("One")
        self.store.create_conversation("Two")
        conversations = self.store.list_conversations()
        self.assertEqual(len(conversations), 2)


if __name__ == "__main__":
    unittest.main()
