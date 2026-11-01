import json
import unittest

from pathlib import Path

from support import temporary_directory

from v.conversations.store import ConversationStore
from v.memory.extractor import MemoryExtractor
from v.memory.queue import ExtractionQueue
from v.memory.store import MemoryStore
from v.providers.base import ChatResult


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1

        if isinstance(self.response, Exception):
            raise self.response

        return ChatResult(
            content=self.response,
            model="test-model",
        )


class MemoryExtractorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        root = Path(self.temp_dir.name)

        self.conversations = ConversationStore(
            root / "conversations.sqlite3"
        )
        self.memory = MemoryStore(root / "memory.sqlite3")
        self.queue = ExtractionQueue(root / "memory.sqlite3")

        self.conversation = self.conversations.create_conversation("Test")
        self.message_id = self.conversations.add_message(
            self.conversation.id,
            "user",
            "Hi, I'm TestUser. I work in construction.",
        )
        self.queue.enqueue(self.conversation.id, self.message_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def candidate(self, **overrides):
        result = {
            "source_message_id": self.message_id,
            "memory_type": "profile",
            "subject": "User",
            "content": "The user's name is TestUser.",
            "memory_key": "user.name",
            "provenance": "explicit",
            "confidence": 0.99,
            "importance": 5,
            "evidence": "I'm TestUser",
        }
        result.update(overrides)
        return result

    def extractor(self, provider):
        return MemoryExtractor(
            provider,
            self.conversations,
            self.memory,
            self.queue,
        )

    async def test_valid_explicit_memory_is_saved(self):
        provider = FakeProvider(
            json.dumps({"memories": [self.candidate()]})
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 1)
        self.assertEqual(report.jobs_completed, 1)
        self.assertEqual(self.memory.count_memories(), 1)
        self.assertEqual(self.queue.count("completed"), 1)

        saved = self.memory.list_memories()[0]
        self.assertEqual(saved.content, "I'm TestUser")
        self.assertEqual(saved.source_message_id, self.message_id)

    async def test_model_paraphrase_is_not_stored_as_fact(self):
        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(
                        content="The user is a professional musician.",
                        evidence="I work in construction",
                        memory_key="user.work",
                    )
                ]
            })
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 1)

        saved = self.memory.list_memories()[0]
        self.assertEqual(saved.content, "I work in construction")
    async def test_ongoing_context_can_be_saved_as_episodic_memory(self):
        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(
                        memory_type="episodic",
                        subject="User's current work context",
                        content="The user currently works in construction.",
                        memory_key="user.current_work_context",
                        confidence=0.96,
                        importance=3,
                        evidence="I work in construction",
                    )
                ]
            })
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 1)
        saved = self.memory.list_memories()[0]
        self.assertEqual(saved.memory_type, "episodic")
        self.assertEqual(saved.content, "I work in construction")

    async def test_unverifiable_evidence_is_rejected(self):
        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(evidence="I am a professional musician")
                ]
            })
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 0)
        self.assertEqual(report.candidates_skipped, 1)
        self.assertEqual(self.memory.count_memories(), 0)

    async def test_inferred_candidate_is_rejected(self):
        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(
                        provenance="inferred",
                        memory_type="inferred_pattern",
                        content="The user is probably an introvert.",
                        evidence="I work in construction",
                    )
                ]
            })
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 0)
        self.assertEqual(report.candidates_skipped, 1)

    async def test_sensitive_candidate_is_rejected(self):
        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(
                        content="The user's religious belief is Muslim.",
                        evidence="I'm TestUser",
                    )
                ]
            })
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 0)
        self.assertEqual(report.candidates_skipped, 1)

    async def test_duplicate_key_does_not_overwrite_existing_memory(self):
        self.memory.create_memory(
            content="The user's name is TestUser.",
            memory_type="profile",
            subject="User",
            memory_key="user.name",
        )

        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(
                        content="The user's name is Richard.",
                        evidence="I'm TestUser",
                    )
                ]
            })
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 0)
        self.assertEqual(report.candidates_skipped, 1)
        self.assertEqual(self.memory.count_memories(), 1)
        self.assertEqual(
            self.memory.list_memories()[0].content,
            "The user's name is TestUser.",
        )

    async def test_invalid_json_fails_jobs_for_retry(self):
        provider = FakeProvider("This is not JSON.")

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.jobs_failed, 1)
        self.assertEqual(self.queue.count("pending"), 1)

    async def test_no_pending_jobs_does_not_call_model(self):
        self.queue.complete(self.message_id)
        provider = FakeProvider('{"memories":[]}')

        report = await self.extractor(provider).process_pending()

        self.assertEqual(provider.calls, 0)
        self.assertEqual(report.jobs_completed, 0)

    async def test_low_confidence_candidate_is_rejected(self):
        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(confidence=0.6)
                ]
            })
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 0)
        self.assertEqual(report.candidates_skipped, 1)


if __name__ == "__main__":
    unittest.main()