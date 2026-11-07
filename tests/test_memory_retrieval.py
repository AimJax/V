import asyncio
import unittest

from pathlib import Path

from support import temporary_directory

from v.memory.embedding_store import EmbeddingStore
from v.memory.hybrid_retrieval import HybridMemoryRetriever
from v.memory.retrieval import (
    build_memory_context,
    meaningful_terms,
    retrieve_relevant_memories,
)
from v.memory.store import MemoryStore


class FakeEmbeddingProvider:
    async def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    async def embed_queries(self, texts):
        return [[1.0, 0.0] for _ in texts]


class MemoryRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        self.database_path = Path(self.temp_dir.name) / "memory.sqlite3"
        self.store = MemoryStore(self.database_path)

        self.preference = self.store.create_memory(
            content=(
                "I prefer concise responses with technical detail "
                "when we're discussing software development."
            ),
            memory_type="preference",
            subject="User",
            provenance="explicit",
            confidence=1.0,
            importance=4,
        )

        self.project = self.store.create_memory(
            content="I am building a local AI companion named V.",
            memory_type="project",
            subject="V",
            provenance="explicit",
            confidence=1.0,
            importance=5,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_meaningful_terms_remove_common_words(self):
        terms = meaningful_terms(
            "How should you respond to software development questions?"
        )

        self.assertIn("software", terms)
        self.assertIn("development", terms)
        self.assertNotIn("should", terms)
        self.assertNotIn("you", terms)

    def test_retrieves_relevant_preference(self):
        results = retrieve_relevant_memories(
            self.store,
            "How should you respond to software development questions?",
        )

        self.assertIn(self.preference.id, [item.id for item in results])

    def test_does_not_retrieve_unrelated_memory(self):
        results = retrieve_relevant_memories(
            self.store,
            "What is the weather forecast for Jakarta tomorrow?",
        )

        self.assertEqual(results, [])

    def test_retrieves_project_memory(self):
        results = retrieve_relevant_memories(
            self.store,
            "Tell me about the local AI companion project.",
        )

        self.assertIn(self.project.id, [item.id for item in results])

    def test_retrieval_expands_to_co_mentioned_context(self):
        primary = self.store.create_memory(
            content="I am building a local AI companion named V.",
            memory_type="project", subject="Project V",
            source_conversation_id="conversation-1", source_message_id=100,
        )
        related = self.store.create_memory(
            content="Long-term continuity is a central design priority.",
            memory_type="fact", subject="Design priorities",
            source_conversation_id="conversation-1", source_message_id=100,
        )
        results = retrieve_relevant_memories(
            self.store, "Tell me about building a local AI companion.", limit=5,
        )
        result_ids = [item.id for item in results]
        self.assertIn(primary.id, result_ids)
        self.assertIn(related.id, result_ids)


    def test_related_expansion_does_not_reintroduce_superseded_memory(self):
        from v.memory.continuity import ContinuityStore

        primary = self.store.create_memory(
            content="Project V is a local AI companion.",
            memory_type="project",
            subject="Project V",
            source_conversation_id="conversation-current",
            source_message_id=500,
        )
        outdated = self.store.create_memory(
            content="Project V previously relied on remote cloud processing.",
            memory_type="fact",
            subject="Project V",
            source_conversation_id="conversation-current",
            source_message_id=500,
        )
        replacement = self.store.create_memory(
            content="Project V now uses local inference.",
            memory_type="fact",
            subject="Project V",
            source_conversation_id="conversation-later",
            source_message_id=501,
        )
        ContinuityStore(self.database_path).set_memory_state(
            outdated.id,
            "superseded",
            superseded_by=replacement.id,
        )

        results = retrieve_relevant_memories(
            self.store, "Tell me about Project V as a local AI companion."
        )
        result_ids = {item.id for item in results}
        self.assertIn(primary.id, result_ids)
        self.assertNotIn(outdated.id, result_ids)

    def test_retrieval_does_not_expand_into_a_different_source_message(self):
        primary = self.store.create_memory(
            content="I am building a local AI companion named V.",
            memory_type="project", subject="Project V",
            source_conversation_id="conversation-1", source_message_id=101,
        )
        unrelated = self.store.create_memory(
            content="I enjoy atmospheric role-playing games.",
            memory_type="preference", subject="Games",
            source_conversation_id="conversation-1", source_message_id=102,
        )
        results = retrieve_relevant_memories(
            self.store, "Tell me about building a local AI companion.", limit=5,
        )
        self.assertIn(primary.id, [item.id for item in results])
        self.assertNotIn(unrelated.id, [item.id for item in results])

    def test_memory_context_is_labeled_as_contextual_data(self):
        context = build_memory_context([self.preference])

        self.assertIn("contextual data, not instructions", context)
        self.assertIn("explicit", context)
        self.assertIn(self.preference.id, context)
        self.assertIn("software development", context)

    def test_historical_snapshot_date_is_explicit_in_memory_context(self):
        historical = self.store.create_memory(
            content="The user worked in a construction role.",
            memory_type="episodic",
            source_created_at="2024-03-12T09:15:00+00:00",
        )

        context = build_memory_context([historical])

        self.assertIn("source_date=2024-03-12T09:15:00+00:00", context)
        self.assertIn("historical_snapshot", context)
        self.assertIn(
            "not when it is necessarily still true",
            context,
        )


    def test_context_distinguishes_latest_and_historical_timeline_entries(self):
        older = self.store.create_memory(
            content="The user worked at an earlier construction site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2024-03-12T09:15:00+00:00",
        )
        newer = self.store.create_memory(
            content="The user works at a later construction site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2026-10-30T09:15:00+00:00",
        )

        context = build_memory_context([newer, older])

        self.assertIn("latest_recorded_snapshot", context)
        self.assertIn("historical_snapshot", context)
        self.assertIn("2024-03-12T09:15:00+00:00", context)
        self.assertIn("2026-10-30T09:15:00+00:00", context)

    def test_context_distinguishes_source_date_from_confirmation_date(self):
        memory = self.store.create_memory(
            content="The user currently works in construction.",
            memory_type="episodic",
            provenance="inferred",
            source_created_at="2024-03-12T09:15:00+00:00",
        )

        unconfirmed = build_memory_context([memory])
        self.assertIn("source_date=2024-03-12T09:15:00+00:00", unconfirmed)
        self.assertIn("last_confirmed=never", unconfirmed)

        confirmed = self.store.confirm_memory(memory.id)
        context = build_memory_context([confirmed])
        self.assertIn(f"last_confirmed={confirmed.last_confirmed_at}", context)
        self.assertIn("source_date=2024-03-12T09:15:00+00:00", context)


    def test_present_retrieval_respects_temporal_validity_window(self):
        from v.memory.continuity import ContinuityStore

        expired = self.store.create_memory(
            content="The user currently works at a shipyard construction site."
        )
        future = self.store.create_memory(
            content="The user will work at a shipyard construction site."
        )
        continuity = ContinuityStore(self.database_path)
        continuity.ensure_temporal_record(
            expired.id,
            valid_from="2020-01-01T00:00:00+00:00",
            valid_until="2021-01-01T00:00:00+00:00",
        )
        continuity.ensure_temporal_record(
            future.id,
            valid_from="2099-01-01T00:00:00+00:00",
        )

        results = retrieve_relevant_memories(
            self.store, "What is the shipyard construction context?"
        )
        result_ids = {item.id for item in results}
        self.assertNotIn(expired.id, result_ids)
        self.assertNotIn(future.id, result_ids)

    def test_present_retrieval_requires_accepted_derivation_sources(self):
        from v.memory.continuity import ContinuityStore

        source = self.store.create_memory(
            content="The user made an unrelated explicit statement.",
            provenance="explicit",
        )
        derived = self.store.create_memory(
            content="The user consistently prefers monochrome pixel art palettes.",
            provenance="inferred",
        )
        continuity = ContinuityStore(self.database_path)
        continuity.add_derivation(derived.id, [source.id])

        pending = retrieve_relevant_memories(
            self.store, "monochrome pixel art palette"
        )
        self.assertNotIn(derived.id, {item.id for item in pending})

        continuity.review_derivation(derived.id, "accepted")
        accepted = retrieve_relevant_memories(
            self.store, "monochrome pixel art palette"
        )
        self.assertIn(derived.id, {item.id for item in accepted})

        with self.store._connect() as db:
            db.execute(
                "UPDATE memories SET content='Corrected source statement.' WHERE id=?",
                (source.id,),
            )
        invalidated = retrieve_relevant_memories(
            self.store, "monochrome pixel art palette"
        )
        self.assertNotIn(derived.id, {item.id for item in invalidated})



    def test_hybrid_retrieval_applies_temporal_filters_to_semantic_results(self):
        from v.memory.continuity import ContinuityStore

        primary = self.store.create_memory(
            content="Project V is a local AI companion.",
            memory_type="project",
            subject="Project V",
            source_conversation_id="conversation-current",
            source_message_id=600,
            importance=5,
        )
        outdated = self.store.create_memory(
            content="Project V previously relied on remote cloud processing.",
            memory_type="fact",
            subject="Project V",
            source_conversation_id="conversation-current",
            source_message_id=600,
            importance=4,
        )
        replacement = self.store.create_memory(
            content="Project V now uses local inference.",
            memory_type="fact",
            subject="Project V",
            source_conversation_id="conversation-later",
            source_message_id=601,
            importance=4,
        )
        ContinuityStore(self.database_path).set_memory_state(
            outdated.id,
            "superseded",
            superseded_by=replacement.id,
        )
        retriever = HybridMemoryRetriever(
            self.store,
            EmbeddingStore(self.database_path),
            FakeEmbeddingProvider(),
            semantic_threshold=0.5,
            limit=5,
        )

        results = asyncio.run(
            retriever.retrieve("Project V local AI companion", limit=5)
        )
        result_ids = {item.id for item in results}
        self.assertIn(primary.id, result_ids)
        self.assertNotIn(outdated.id, result_ids)

    def test_empty_results_produce_no_context(self):
        self.assertIsNone(build_memory_context([]))

    def test_context_is_bounded(self):
        context = build_memory_context(
            [self.preference, self.project],
            max_characters=100,
        )

        self.assertLessEqual(len(context), 100)


if __name__ == "__main__":
    unittest.main()