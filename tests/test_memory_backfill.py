import asyncio
import json
import unittest

from pathlib import Path

from support import temporary_directory

from v.conversations.store import ConversationStore
from v.memory.backfill import (
    MemoryBackfillRunner,
    MemoryBackfillStore,
    MemoryReviewService,
)
from v.memory.extractor import MemoryExtractor
from v.memory.queue import ExtractionQueue
from v.memory.store import MemoryStore
from v.providers.base import ChatResult


class FakeProvider:
    def __init__(self):
        self.calls = 0
        self.cancel_on_call = None
        self.memory_type = "episodic"

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.cancel_on_call == self.calls:
            raise asyncio.CancelledError()

        source = json.loads(messages[1].content)
        candidates = []
        for item in source:
            message_id = item["source_message_id"]
            evidence = item["user_message"]
            candidates.append(
                {
                    "source_message_id": message_id,
                    "memory_type": self.memory_type,
                    "subject": "User context",
                    "content": f"Remembered context from message {message_id}.",
                    "memory_key": f"backfill.message.{message_id}",
                    "provenance": "explicit",
                    "confidence": 0.99,
                    "importance": 4,
                    "evidence": evidence,
                }
            )
        return ChatResult(
            content=json.dumps({"memories": candidates}),
            model="test-model",
        )


class MemoryBackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        root = Path(self.temp_dir.name)
        self.conversations = ConversationStore(root / "conversations.sqlite3")
        self.memory = MemoryStore(root / "memory.sqlite3")
        self.queue = ExtractionQueue(root / "memory.sqlite3")
        self.review = MemoryBackfillStore(root / "memory.sqlite3")
        self.provider = FakeProvider()
        self.conversation = self.conversations.create_conversation("History")

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_user_message(self, text):
        return self.conversations.add_message(
            self.conversation.id,
            "user",
            text,
        )

    def make_runner(self, batch_size=5):
        extractor = MemoryExtractor(
            self.provider,
            self.conversations,
            self.memory,
            self.queue,
        )
        return MemoryBackfillRunner(
            self.conversations,
            extractor,
            self.memory,
            self.review,
            batch_size=batch_size,
        )

    async def test_status_open_does_not_pause_a_live_scan_owner(self):
        self.add_user_message("I currently work in construction.")
        self.assertTrue(self.review.acquire_run_lock())
        run = self.review.create_run(
            upper_message_id=self.conversations.max_user_message_id(),
            total_messages=1,
        )
        self.review.set_run_status(run["id"], "running")

        second_view = MemoryBackfillStore(self.memory.database_path)
        self.assertEqual(second_view.latest_run()["status"], "running")
        self.assertFalse(second_view.acquire_run_lock())

        self.review.release_run_lock()
        recovered_view = MemoryBackfillStore(self.memory.database_path)
        self.assertEqual(recovered_view.latest_run()["status"], "paused")

    async def test_one_source_message_can_propose_multiple_episodic_snapshots(self):
        message_id = self.add_user_message(
            "I worked at Site A last year. I now work at Site B."
        )
        run = self.review.create_run(
            upper_message_id=message_id,
            total_messages=1,
        )
        self.review.set_run_status(run["id"], "running")
        proposals = [
            {
                "source_message_id": message_id,
                "source_conversation_id": self.conversation.id,
                "memory_key": "user.work_context",
                "memory_type": "episodic",
                "evidence": "I worked at Site A last year.",
            },
            {
                "source_message_id": message_id,
                "source_conversation_id": self.conversation.id,
                "memory_key": "user.work_context",
                "memory_type": "episodic",
                "evidence": "I now work at Site B.",
            },
        ]

        result = self.review.save_batch(
            run["id"],
            last_message_id=message_id,
            processed_messages=1,
            candidates=proposals,
            candidates_skipped=0,
        )

        self.assertEqual(result["candidates_found"], 2)
        pending = self.review.list_candidates(status="pending")
        self.assertEqual(len(pending), 2)
        self.assertEqual(
            {item["payload"]["evidence"] for item in pending},
            {
                "I worked at Site A last year.",
                "I now work at Site B.",
            },
        )

    async def test_backfill_creates_review_proposals_without_saving_memories(self):
        first_id = self.add_user_message("I currently work in construction.")
        self.conversations.add_message(
            self.conversation.id,
            "assistant",
            "Understood.",
        )
        self.add_user_message("I am learning rigging and crane operations.")

        progress = []
        result = await self.make_runner(batch_size=1).run(
            on_progress=progress.append
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["processed_messages"], 2)
        self.assertEqual(result["candidates_found"], 2)
        self.assertEqual(self.memory.count_memories(), 0)
        self.assertEqual(len(progress), 3)
        self.assertEqual(progress[0]["status"], "running")

        candidates = self.review.list_candidates(status="pending")
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["payload"]["source_message_id"], first_id)
        self.assertEqual(
            candidates[0]["payload"]["evidence"],
            "I currently work in construction.",
        )
        self.assertTrue(candidates[0]["payload"]["source_created_at"])
        self.assertEqual(
            candidates[0]["payload"]["model_content"],
            f"Remembered context from message {first_id}.",
        )

    async def test_cancelled_scan_resumes_from_last_committed_batch(self):
        self.add_user_message("I currently work in construction.")
        self.add_user_message("I am learning crane operations.")
        self.provider.cancel_on_call = 2
        runner = self.make_runner(batch_size=1)

        with self.assertRaises(asyncio.CancelledError):
            await runner.run()

        paused = self.review.latest_run()
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["processed_messages"], 1)
        self.assertEqual(self.review.list_candidates(status="pending")[0]["payload"]["source_message_id"],
                         self.conversations.list_user_messages(limit=1)[0].id)

        self.provider.cancel_on_call = None
        resumed = await runner.run()

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["processed_messages"], 2)
        self.assertEqual(resumed["candidates_found"], 2)
        self.assertEqual(self.provider.calls, 3)

    async def test_new_scan_requires_explicit_opt_in_after_completion(self):
        self.add_user_message("I prefer shoegaze music.")
        runner = self.make_runner()
        await runner.run()

        with self.assertRaisesRegex(RuntimeError, "--new-run"):
            await runner.run()

        second = await runner.run(new_run=True)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(self.review.latest_run()["id"], second["id"])

    async def test_approval_creates_memory_and_retains_review_provenance(self):
        message_id = self.add_user_message("I prefer shoegaze and slowcore.")
        await self.make_runner().run()
        candidate = self.review.list_candidates(status="pending")[0]

        memory = MemoryReviewService(
            self.memory,
            self.review,
        ).approve_candidate(
            candidate["id"],
            changes={"content": "The user prefers shoegaze and slowcore music."},
        )

        self.assertEqual(self.memory.count_memories(), 1)
        self.assertEqual(memory.source_message_id, message_id)
        self.assertEqual(memory.source_conversation_id, self.conversation.id)
        source_message = self.conversations.get_message_record(message_id)
        self.assertEqual(memory.source_created_at, source_message.created_at)
        self.assertEqual(memory.content, "The user prefers shoegaze and slowcore music.")
        self.assertEqual(memory.evidence, "I prefer shoegaze and slowcore.")
        reviewed = self.review.get_candidate(candidate["id"])
        self.assertEqual(reviewed["status"], "approved")
        self.assertEqual(reviewed["approved_memory_id"], memory.id)

    async def test_duplicate_key_is_never_allowed_to_overwrite_existing_memory(self):
        self.provider.memory_type = "preference"
        self.add_user_message("I prefer shoegaze music.")
        await self.make_runner().run()
        candidate = self.review.list_candidates(status="pending")[0]
        existing = self.memory.create_memory(
            content="I prefer jazz.",
            memory_type="preference",
            subject="User",
            memory_key=candidate["payload"]["memory_key"],
            source_conversation_id="older-conversation",
            source_message_id=999,
            evidence="I prefer jazz.",
        )

        with self.assertRaisesRegex(ValueError, "conflicts with existing memory"):
            MemoryReviewService(
                self.memory,
                self.review,
            ).approve_candidate(candidate["id"])

        self.assertEqual(self.memory.count_memories(), 1)
        self.assertEqual(self.memory.get_memory(existing.id).content, "I prefer jazz.")
        reviewed = self.review.get_candidate(candidate["id"])
        self.assertEqual(reviewed["status"], "duplicate")
        self.assertEqual(reviewed["approved_memory_id"], existing.id)

    async def test_rejection_is_audited_and_not_deleted(self):
        self.add_user_message("I enjoy quiet coastal walks.")
        await self.make_runner().run()
        candidate = self.review.list_candidates(status="pending")[0]

        MemoryReviewService(
            self.memory,
            self.review,
        ).reject_candidate(candidate["id"], reason="Too temporary.")

        rejected = self.review.get_candidate(candidate["id"])
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["review_note"], "Too temporary.")
        self.assertEqual(
            len(self.review.list_candidates(status="rejected")),
            1,
        )
        self.assertEqual(self.memory.count_memories(), 0)

    async def test_failed_provider_request_does_not_advance_checkpoint(self):
        self.add_user_message("I currently work in construction.")
        self.provider.cancel_on_call = 1
        # A provider cancellation represents an interrupted request. It must
        # pause the run and leave the current page available for a retry.
        with self.assertRaises(asyncio.CancelledError):
            await self.make_runner().run()

        run = self.review.latest_run()
        self.assertEqual(run["status"], "paused")
        self.assertEqual(run["processed_messages"], 0)
        self.assertEqual(run["cursor_message_id"], 0)


if __name__ == "__main__":
    unittest.main()
