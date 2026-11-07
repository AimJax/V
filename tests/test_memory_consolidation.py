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
    def __init__(self, content: str, on_call=None) -> None:
        self.content = content
        self.calls = 0
        self.last_messages = None
        self.on_call = on_call

    async def chat(self, messages, *, temperature: float, max_tokens: int):
        self.calls += 1
        self.last_messages = messages
        if self.on_call is not None:
            self.on_call()
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
        self.assertEqual(
            [self.store.get_memory(item.id).content for item in self.sources],
            [item.content for item in self.sources],
        )
        pattern = self.store.list_memories(memory_type="inferred_pattern")[0]
        sources = self.continuity.derivation_sources(pattern.id)
        self.assertEqual(len(sources), 3)
        self.assertEqual({item["state"] for item in sources}, {"pending"})
        self.assertEqual(
            {item.id for item in self.store.list_memory_evidence(pattern.id)},
            {item.id for item in self.sources},
        )


    async def test_contradictory_sources_can_be_rejected_without_summary(self):
        for source in self.sources:
            self.store.delete_memory(source.id)
        contradictory = [
            ("conversation-a", 301, "The user prefers short answers."),
            ("conversation-a", 302, "The user prefers detailed, exhaustive answers."),
            ("conversation-b", 303, "The user prefers short answers for technical topics."),
        ]
        sources = []
        for conversation, message_id, content in contradictory:
            sources.append(self.store.create_memory(
                content=content,
                memory_type="episodic",
                subject="Communication",
                memory_key="preference.answer_style",
                provenance="explicit",
                source_conversation_id=conversation,
                source_message_id=message_id,
                source_created_at="2026-10-01T10:00:00+00:00",
                evidence=content,
            ))

        provider = FakeProvider(json.dumps({
            "summary": "",
            "confidence": 0.0,
            "importance": 1,
        }))
        report = await MemoryConsolidator(
            provider, self.store, self.continuity
        ).run()

        self.assertEqual(report.groups_examined, 1)
        self.assertEqual(report.summaries_created, 0)
        self.assertEqual(report.duplicates_skipped, 0)
        self.assertEqual(report.groups_skipped, 1)
        self.assertEqual(self.store.count_inferred_patterns(), 0)
        self.assertIn("Preserve meaningful disagreement", provider.last_messages[0].content)
        self.assertEqual(
            [self.store.get_memory(item.id).content for item in sources],
            [item.content for item in sources],
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



    async def test_episodic_timeline_consolidation_preserves_chronological_sources(self):
        for source in self.sources:
            self.store.delete_memory(source.id)
        episodes = [
            ("conversation-a", 201, "2026-09-01T10:00:00+00:00", "Project V began as a prototype."),
            ("conversation-a", 202, "2026-10-01T10:00:00+00:00", "Project V gained persistent local memory."),
            ("conversation-b", 203, "2026-11-01T10:00:00+00:00", "Project V gained review-gated continuity."),
        ]
        for conversation, message_id, timestamp, content in episodes:
            self.store.create_memory(
                content=content,
                memory_type="episodic",
                subject="Project V",
                memory_key="project.v.timeline",
                provenance="explicit",
                source_conversation_id=conversation,
                source_message_id=message_id,
                source_created_at=timestamp,
                evidence=content,
            )
        provider = FakeProvider(json.dumps({
            "summary": "Project V evolved from a prototype into a system with local memory and review-gated continuity.",
            "confidence": 0.93,
            "importance": 4,
        }))
        report = await MemoryConsolidator(
            provider, self.store, self.continuity
        ).run()

        self.assertEqual(report.summaries_created, 1)
        supplied = json.loads(provider.last_messages[1].content)
        self.assertEqual(
            [item["source_date"] for item in supplied],
            [item[2] for item in episodes],
        )
        self.assertTrue(all(item["memory_key"] == "project.v.timeline" for item in supplied))

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


    async def test_cancellation_after_model_response_prevents_summary_write(self):
        cancelled = asyncio.Event()
        provider = FakeProvider(
            json.dumps({
                "summary": "The user prefers restrained, practical interface aesthetics.",
                "confidence": 0.94,
                "importance": 4,
            }),
            on_call=cancelled.set,
        )
        consolidator = MemoryConsolidator(provider, self.store, self.continuity)

        report = await consolidator.run(cancel_event=cancelled)

        self.assertTrue(report.cancelled)
        self.assertEqual(provider.calls, 1)
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
