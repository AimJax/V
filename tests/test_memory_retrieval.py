import unittest

from pathlib import Path

from support import temporary_directory

from v.memory.retrieval import (
    build_memory_context,
    meaningful_terms,
    retrieve_relevant_memories,
)
from v.memory.store import MemoryStore


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