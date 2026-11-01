import json
import unittest

from pathlib import Path

from support import temporary_directory

from v.conversations.store import ConversationStore
from v.memory.backfill import MemoryBackfillStore
from v.memory.extractor import MemoryExtractor, _split_text_windows
from v.memory.queue import ExtractionQueue
from v.memory.store import MemoryStore
from v.providers.base import ChatResult


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.last_messages = None

    async def chat(self, messages, **kwargs):
        self.calls += 1
        self.last_messages = list(messages)

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

    def test_long_message_windows_overlap_without_dropping_source_text(self):
        source = (
            "Opening statement. "
            + ("A detailed historical circumstance with exact context. " * 260)
            + "Final statement."
        )
        windows = _split_text_windows(
            source,
            max_characters=1200,
            overlap_characters=100,
        )

        self.assertGreater(len(windows), 1)
        self.assertTrue(all(len(window) <= 1200 for window in windows))
        self.assertTrue(
            all(
                windows[index][-100:] == windows[index + 1][:100]
                for index in range(len(windows) - 1)
            )
        )
        reconstructed = windows[0] + "".join(
            window[100:] for window in windows[1:]
        )
        self.assertEqual(reconstructed, source)

    async def test_long_message_extraction_deduplicates_overlapping_windows(self):
        class WindowProvider:
            def __init__(self):
                self.calls = 0
                self.request_sizes = []

            async def chat(self, messages, **kwargs):
                self.calls += 1
                payload = json.loads(messages[1].content)
                self.request_sizes.append(
                    sum(len(item["user_message"]) for item in payload)
                )
                return ChatResult(
                    content=json.dumps({
                        "memories": [
                            {
                                "source_message_id": item["source_message_id"],
                                "memory_type": "profile",
                                "subject": "User",
                                "content": "The user's name is TestUser.",
                                "memory_key": "user.name",
                                "provenance": "explicit",
                                "confidence": 0.99,
                                "importance": 5,
                                "evidence": "I'm TestUser",
                            }
                            for item in payload
                        ]
                    }),
                    model="test-model",
                )

        long_text = (
            "Hi, I'm TestUser. "
            + ("A detailed account of an important long-term circumstance. " * 500)
        )
        message_id = self.conversations.add_message(
            self.conversation.id,
            "user",
            long_text,
        )
        message = self.conversations.get_message_record(message_id)
        provider = WindowProvider()

        candidates, skipped = await self.extractor(provider).extract_candidates(
            [message]
        )

        self.assertGreater(provider.calls, 1)
        self.assertTrue(all(size <= 10000 for size in provider.request_sizes))
        self.assertEqual(len(candidates), 1)
        self.assertGreater(skipped, 0)
        self.assertEqual(candidates[0]["evidence"], "I'm TestUser")
        self.assertEqual(candidates[0]["source_message_id"], message_id)
        self.assertEqual(candidates[0]["source_created_at"], message.created_at)

    async def test_extraction_receives_limited_surrounding_context(self):
        self.conversations.add_message(
            self.conversation.id,
            "assistant",
            "Are you still working in that construction role?",
        )
        provider = FakeProvider(
            json.dumps({"memories": [self.candidate()]})
        )

        report = await self.extractor(provider).process_pending()

        self.assertEqual(report.memories_created, 1)
        source_payload = json.loads(provider.last_messages[1].content)[0]
        self.assertEqual(source_payload["source_message_id"], self.message_id)
        self.assertEqual(
            source_payload["user_message"],
            "Hi, I'm TestUser. I work in construction.",
        )
        self.assertEqual(
            source_payload["surrounding_context"][0]["role"],
            "assistant",
        )
        self.assertEqual(
            source_payload["surrounding_context"][0]["content"],
            "Are you still working in that construction role?",
        )
        saved = self.memory.list_memories()[0]
        self.assertEqual(saved.evidence, "I'm TestUser")
        self.assertEqual(saved.source_message_id, self.message_id)

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
        source_message = self.conversations.get_message_record(self.message_id)
        self.assertEqual(saved.source_created_at, source_message.created_at)

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

    async def test_stable_key_conflict_is_queued_for_review_without_overwrite(self):
        existing = self.memory.create_memory(
            content="The user worked in retail.",
            memory_type="fact",
            subject="User work",
            memory_key="user.work_context",
            source_conversation_id="older-conversation",
            source_message_id=999,
            evidence="I worked in retail.",
        )
        provider = FakeProvider(
            json.dumps({
                "memories": [
                    self.candidate(
                        memory_type="fact",
                        subject="User work",
                        content="The user works in construction.",
                        memory_key="user.work_context",
                        evidence="I work in construction",
                    )
                ]
            })
        )
        review_store = MemoryBackfillStore(self.memory.database_path)
        extractor = MemoryExtractor(
            provider,
            self.conversations,
            self.memory,
            self.queue,
            conflict_store=review_store,
        )

        report = await extractor.process_pending()

        self.assertEqual(report.memories_created, 0)
        self.assertEqual(report.conflicts_queued, 1)
        self.assertEqual(report.candidates_skipped, 0)
        self.assertEqual(self.memory.count_memories(), 1)
        self.assertEqual(self.memory.get_memory(existing.id).content, "The user worked in retail.")

        pending = review_store.list_candidates(status="pending")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["source_kind"], "conflict")
        self.assertEqual(pending[0]["payload"]["review_kind"], "key_conflict")
        self.assertEqual(
            pending[0]["payload"]["conflict"]["existing_memory"]["id"],
            existing.id,
        )

    async def test_exact_same_source_conflict_is_not_queued_again(self):
        source = self.conversations.get_message_record(self.message_id)
        existing = self.memory.create_memory(
            content="I'm TestUser",
            memory_type="profile",
            subject="User",
            memory_key="user.name",
            source_conversation_id=source.conversation_id,
            source_message_id=source.id,
            source_created_at=source.created_at,
            evidence="I'm TestUser",
        )
        provider = FakeProvider(
            json.dumps({"memories": [self.candidate()]})
        )
        review_store = MemoryBackfillStore(self.memory.database_path)
        extractor = MemoryExtractor(
            provider,
            self.conversations,
            self.memory,
            self.queue,
            conflict_store=review_store,
        )

        report = await extractor.process_pending()

        self.assertEqual(report.conflicts_queued, 0)
        self.assertEqual(report.candidates_skipped, 1)
        self.assertEqual(review_store.list_candidates(status="pending"), [])
        self.assertEqual(self.memory.get_memory(existing.id).content, "I'm TestUser")

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