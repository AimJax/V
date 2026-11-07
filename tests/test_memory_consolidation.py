from __future__ import annotations

import asyncio
import json
import unittest

from pathlib import Path
from types import SimpleNamespace

from support import temporary_directory

from v.memory.consolidation import MemoryConsolidator
from v.memory.continuity import ContinuityStore
from v.memory.store import MemoryStore


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def chat(self, messages, *, temperature: float, max_tokens: int):
        self.calls += 1
        return SimpleNamespace(content=self.content)


class MemoryConsolidationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        self.database_path = Path(self.temp_dir.name) / "memory.sqlite3"
        self.store = MemoryStore(self.database_path)
        self.continuity = ContinuityStore(self.database_path)
        self.sources = []
        for index, conversation in enumerate(
            ("conversation-a", "conversation-a", "conversation-b"),
            start=1,
        ):
            self.sources.append(
                self.store.create_memory(
                    content=f"Explicit preference evidence {index} about interface aesthetics.",
                    memory_type="preference",
                    subject="User",
                    provenance="explicit",
                    source_conversation_id=conversation,
                    source_message_id=100 + index,
                    source_created_at=f"2026-10-{index:02d}T10:00:00+00:00",
                    evidence=f"Preference statement {index}.",
                )
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_consolidation_creates_pending_evidence_linked_summary(self):
        provider = FakeProvider(json.dumps({
            "summary": "The user prefers restrained, practical interface aesthetics.",
            "confidence": 0.94,
            "importance": 4,
        }))
        consolidator = MemoryConsolidator(provider, self.store, self.continuity)

        report = await consolidator.run()

        self.assertEqual(report.groups_examined, 1)
        self.assertEqual(report.summaries_created, 1)
        self.assertEqual(provider.calls, 1)
        pattern = self.store.list_memories(memory_type="inferred_pattern")[0]
        sources = self.continuity.derivation_sources(pattern.id)
        self.assertEqual(len(sources), 3)
        self.assertEqual({item["state"] for item in sources}, {"pending"})
        self.assertEqual(
            {item.id for item in self.store.list_memory_evidence(pattern.id)},
            {item.id for item in self.sources},
        )

    async def test_pending_summary_is_not_retrieved_until_accepted(self):
        from v.memory.retrieval import retrieve_relevant_memories

        provider = FakeProvider(json.dumps({
            "summary": "The user prefers restrained, practical interface aesthetics.",
            "confidence": 0.94,
            "importance": 4,
        }))
        consolidator = MemoryConsolidator(provider, self.store, self.continuity)
        await consolidator.run()
        pattern = self.store.list_memories(memory_type="inferred_pattern")[0]

        pending = retrieve_relevant_memories(
            self.store, "restrained practical interface aesthetics"
        )
        self.assertNotIn(pattern.id, {item.id for item in pending})

        self.continuity.review_derivation(pattern.id, "accepted")
        accepted = retrieve_relevant_memories(
            self.store, "restrained practical interface aesthetics"
        )
        self.assertIn(pattern.id, {item.id for item in accepted})

    async def test_existing_summary_is_not_duplicated(self):
        provider = FakeProvider(json.dumps({
            "summary": "The user prefers restrained, practical interface aesthetics.",
            "confidence": 0.94,
            "importance": 4,
        }))
        consolidator = MemoryConsolidator(provider, self.store, self.continuity)

        first = await consolidator.run()
        second = await consolidator.run()

        self.assertEqual(first.summaries_created, 1)
        self.assertEqual(second.duplicates_skipped, 1)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.store.count_inferred_patterns(), 1)


    async def test_new_accepted_summary_supersedes_older_summary_for_same_topic(self):
        from v.memory.retrieval import retrieve_relevant_memories

        provider = FakeProvider(json.dumps({
            "summary": "The user prefers restrained, practical interface aesthetics.",
            "confidence": 0.94,
            "importance": 4,
        }))
        consolidator = MemoryConsolidator(provider, self.store, self.continuity)
        await consolidator.run()
        old_pattern = self.store.list_memories(memory_type="inferred_pattern")[0]
        self.continuity.review_derivation(old_pattern.id, "accepted")

        self.store.create_memory(
            content="The user again requested a restrained, practical interface.",
            memory_type="preference",
            subject="User",
            provenance="explicit",
            source_conversation_id="conversation-b",
            source_message_id=104,
            source_created_at="2026-10-04T10:00:00+00:00",
            evidence="Please keep the interface restrained and practical.",
        )
        second = await consolidator.run()
        self.assertEqual(second.summaries_created, 1)
        patterns = self.store.list_memories(memory_type="inferred_pattern")
        new_pattern = next(item for item in patterns if item.id != old_pattern.id)

        self.assertEqual(self.continuity.temporal_record(old_pattern.id)["state"], "current")
        self.continuity.review_derivation(new_pattern.id, "accepted")
        old_state = self.continuity.temporal_record(old_pattern.id)
        self.assertEqual(old_state["state"], "superseded")
        self.assertEqual(old_state["superseded_by"], new_pattern.id)

        results = retrieve_relevant_memories(
            self.store, "restrained practical interface aesthetics"
        )
        result_ids = {item.id for item in results}
        self.assertNotIn(old_pattern.id, result_ids)
        self.assertIn(new_pattern.id, result_ids)

    async def test_cancellation_prevents_model_work(self):
        provider = FakeProvider("{}")
        consolidator = MemoryConsolidator(provider, self.store, self.continuity)
        cancelled = asyncio.Event()
        cancelled.set()

        report = await consolidator.run(cancel_event=cancelled)

        self.assertTrue(report.cancelled)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(self.store.count_inferred_patterns(), 0)

    async def test_expired_source_records_do_not_form_a_current_summary(self):
        for source in self.sources:
            self.continuity.update_temporal_record(
                source.id,
                "expired",
                valid_until="2020-01-01T00:00:00+00:00",
            )
        provider = FakeProvider("{}")
        consolidator = MemoryConsolidator(provider, self.store, self.continuity)

        report = await consolidator.run()

        self.assertEqual(report.groups_examined, 0)
        self.assertEqual(provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
