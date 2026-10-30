import unittest

from pathlib import Path

from support import temporary_directory

from v.memory.store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        self.database_path = Path(self.temp_dir.name) / "memory_test.sqlite3"
        self.store = MemoryStore(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_retrieve_explicit_memory(self):
        memory = self.store.create_memory(
            content="The user prefers concise answers.",
            memory_type="preference",
            subject="User",
            provenance="explicit",
            confidence=1.0,
            importance=5,
            source_conversation_id="conversation-1",
            source_message_id=7,
            evidence="Keep your answers concise.",
        )

        result = self.store.get_memory(memory.id)

        self.assertIsNotNone(result)
        self.assertEqual(result.content, "The user prefers concise answers.")
        self.assertEqual(result.provenance, "explicit")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.source_message_id, 7)
        self.assertIsNotNone(result.last_confirmed_at)

    def test_inferred_memory_has_distinct_provenance(self):
        memory = self.store.create_memory(
            content="The user may prefer working late.",
            memory_type="inferred_pattern",
            provenance="inferred",
            confidence=0.65,
        )

        self.assertEqual(memory.provenance, "inferred")
        self.assertEqual(memory.confidence, 0.65)
        self.assertIsNone(memory.last_confirmed_at)

    def test_invalid_confidence_is_rejected(self):
        for confidence in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(confidence=confidence):
                with self.assertRaises(ValueError):
                    self.store.create_memory(
                        content="Invalid confidence test",
                        confidence=confidence,
                    )

    def test_invalid_memory_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.create_memory(
                content="Test",
                memory_type="invalid",
            )

    def test_memory_key_is_normalized_and_unique(self):
        first = self.store.create_memory(
            content="The user enjoys shoegaze.",
            memory_type="preference",
            memory_key=" Music Genre ",
        )

        self.assertEqual(first.memory_key, "music genre")

        with self.assertRaises(ValueError):
            self.store.create_memory(
                content="The user enjoys jazz.",
                memory_type="preference",
                memory_key="MUSIC GENRE",
            )

    def test_search_finds_memory(self):
        self.store.create_memory(
            content="The user enjoys shoegaze and slowcore music.",
            memory_type="preference",
            subject="Music",
        )

        results = self.store.search_memories("shoegaze slowcore")

        self.assertEqual(len(results), 1)
        self.assertIn("shoegaze", results[0].content)

    def test_search_index_updates_after_correction(self):
        memory = self.store.create_memory(
            content="The user likes jazz.",
            memory_type="preference",
        )

        self.store.update_memory(
            memory.id,
            content="The user likes shoegaze.",
        )

        self.assertEqual(
            len(self.store.search_memories("jazz")),
            0,
        )
        self.assertEqual(
            len(self.store.search_memories("shoegaze")),
            1,
        )

    def test_search_index_removes_deleted_memory(self):
        memory = self.store.create_memory(
            content="The user likes ambient music.",
        )

        self.assertTrue(self.store.delete_memory(memory.id))
        self.assertEqual(len(self.store.search_memories("ambient")), 0)
        self.assertIsNone(self.store.get_memory(memory.id))
        self.assertFalse(self.store.delete_memory(memory.id))

    def test_list_can_filter_by_provenance(self):
        self.store.create_memory(
            content="Explicit fact.",
            provenance="explicit",
        )
        self.store.create_memory(
            content="Inferred pattern.",
            provenance="inferred",
            confidence=0.7,
        )

        explicit = self.store.list_memories(provenance="explicit")
        inferred = self.store.list_memories(provenance="inferred")

        self.assertEqual(len(explicit), 1)
        self.assertEqual(len(inferred), 1)

    def test_update_preserves_original_source(self):
        memory = self.store.create_memory(
            content="The user enjoys rock.",
            source_conversation_id="conversation-2",
            source_message_id=9,
        )

        updated = self.store.update_memory(
            memory.id,
            content="The user enjoys alternative rock.",
            importance=5,
        )

        self.assertEqual(
            updated.source_conversation_id,
            "conversation-2",
        )
        self.assertEqual(updated.source_message_id, 9)
        self.assertEqual(updated.importance, 5)
        self.assertEqual(updated.created_at, memory.created_at)

    def test_empty_search_returns_no_results(self):
        self.store.create_memory(content="Testing search.")

        self.assertEqual(self.store.search_memories("!!!"), [])

    def test_count_memories(self):
        self.assertEqual(self.store.count_memories(), 0)

        self.store.create_memory(content="One")
        self.store.create_memory(content="Two")

        self.assertEqual(self.store.count_memories(), 2)


if __name__ == "__main__":
    unittest.main()