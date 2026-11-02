import sqlite3
import unittest

from contextlib import closing
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

    def test_read_only_store_does_not_initialize_or_modify_database(self):
        original = self.store.create_memory(
            content="A memory that must remain unchanged.",
        )
        modified_before = self.database_path.stat().st_mtime_ns

        read_only = MemoryStore(self.database_path, read_only=True)
        loaded = read_only.get_memory(original.id)

        self.assertEqual(loaded.content, original.content)
        self.assertEqual(self.database_path.stat().st_mtime_ns, modified_before)
        with self.assertRaises(sqlite3.OperationalError):
            read_only.create_memory(content="This write must be rejected.")
        self.assertEqual(self.store.count_memories(), 1)
        self.assertEqual(self.database_path.stat().st_mtime_ns, modified_before)

    def test_read_only_store_reads_legacy_schema_without_migrating(self):
        memory = self.store.create_memory(
            content="A legacy-schema memory about local AI development.",
            memory_type="project",
            subject="Project",
        )
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "ALTER TABLE memories DROP COLUMN source_created_at"
            )
            connection.commit()

        modified_before = self.database_path.stat().st_mtime_ns
        read_only = MemoryStore(self.database_path, read_only=True)

        loaded = read_only.get_memory(memory.id)
        listed = read_only.list_memories(limit=10)
        lexical_any = read_only.search_memories_any("local AI", limit=10)
        lexical_all = read_only.search_memories("local AI", limit=10)

        self.assertEqual(loaded.id, memory.id)
        self.assertIsNone(loaded.source_created_at)
        self.assertEqual([item.id for item in listed], [memory.id])
        self.assertEqual([item.id for item in lexical_any], [memory.id])
        self.assertEqual([item.id for item in lexical_all], [memory.id])
        self.assertEqual(self.database_path.stat().st_mtime_ns, modified_before)

        with closing(sqlite3.connect(self.database_path)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(memories)")
            }
        self.assertNotIn("source_created_at", columns)

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

    def test_original_source_date_survives_storage_and_retrieval(self):
        source_date = "2025-05-18T12:30:00+00:00"
        memory = self.store.create_memory(
            content="The user was working in a construction role.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_conversation_id="conversation-old",
            source_message_id=24,
            source_created_at=source_date,
            evidence="I was working in construction.",
        )

        loaded = self.store.get_memory(memory.id)

        self.assertEqual(loaded.source_created_at, source_date)
        self.assertEqual(
            self.store.get_memory_by_key(memory.memory_key),
            loaded,
        )

    def test_episodic_records_can_share_a_key_and_form_a_timeline(self):
        older = self.store.create_memory(
            content="The user worked at a coastal industrial site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2024-03-12T09:15:00+00:00",
            importance=4,
        )
        newer = self.store.create_memory(
            content="The user now works in a different construction role.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2026-10-30T09:15:00+00:00",
            importance=4,
        )

        self.assertNotEqual(older.id, newer.id)
        self.assertEqual(
            self.store.get_memory_by_key("user.work_context"),
            newer,
        )
        timeline = self.store.list_memories(memory_type="episodic")
        matching = [
            item for item in timeline
            if item.memory_key == "user.work_context"
        ]
        self.assertEqual(
            [item.source_created_at for item in matching],
            [
                "2026-10-30T09:15:00+00:00",
                "2024-03-12T09:15:00+00:00",
            ],
        )

        self.store.create_memory(
            content="Another stable profile statement.",
            memory_type="profile",
            memory_key="user.name",
        )
        with self.assertRaises(ValueError):
            self.store.create_memory(
                content="Conflicting stable profile statement.",
                memory_type="profile",
                memory_key="user.name",
            )


    def test_episodic_timeline_orders_instants_across_utc_offsets(self):
        lexically_later_but_earlier = self.store.create_memory(
            content="The user worked at the first site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2026-01-01T00:30:00+02:00",
        )
        chronologically_later = self.store.create_memory(
            content="The user worked at the second site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2025-12-31T23:00:00+00:00",
        )

        self.assertEqual(
            self.store.get_memory_by_key("user.work_context"),
            chronologically_later,
        )
        timeline = [
            item for item in self.store.list_memories(memory_type="episodic")
            if item.memory_key == "user.work_context"
        ]
        self.assertEqual(
            [item.id for item in timeline],
            [chronologically_later.id, lexically_later_but_earlier.id],
        )

    def test_invalid_original_source_date_is_rejected(self):
        for value in (
            "not-a-date",
            "2025-05-18T12:30:00",
            123,
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.store.create_memory(
                        content="Historical context.",
                        source_created_at=value,
                    )

    def test_migrates_existing_schema_without_losing_memories(self):
        original = self.store.create_memory(
            content="An existing memory.",
            memory_key="existing",
        )
        with closing(self.store._connect()) as connection:
            with connection:
                connection.execute(
                    "ALTER TABLE memories DROP COLUMN source_created_at"
                )
                connection.execute("DROP INDEX idx_memories_key")
                connection.execute(
                    """
                    CREATE UNIQUE INDEX idx_memories_key
                    ON memories(memory_key)
                    WHERE memory_key IS NOT NULL
                    """
                )
                connection.execute("PRAGMA user_version = 1")

        migrated = MemoryStore(self.database_path)
        restored = migrated.get_memory(original.id)

        self.assertEqual(restored.content, "An existing memory.")
        self.assertIsNone(restored.source_created_at)
        with closing(migrated._connect()) as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(memories)")
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertIn("source_created_at", columns)
        self.assertEqual(version, 3)
        migrated.create_memory(
            content="A dated episodic snapshot sharing the old fact key.",
            memory_type="episodic",
            memory_key="existing",
            source_created_at="2026-10-31T10:00:00+00:00",
        )
        self.assertEqual(migrated.count_memories(), 2)

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

    def test_invalid_memory_key_type_is_rejected(self):
        with self.assertRaises(TypeError):
            self.store.create_memory(
                content="Invalid key test.",
                memory_key=123,
            )

    def test_boolean_confidence_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.create_memory(
                content="Invalid confidence test.",
                confidence=True,
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

    def test_confirm_memory_updates_only_confirmation_and_audit_timestamps(self):
        memory = self.store.create_memory(
            content="The user currently works in construction.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_conversation_id="conversation-confirm",
            source_message_id=77,
            source_created_at="2024-03-12T09:15:00+00:00",
            evidence="I currently work in construction.",
        )

        confirmed = self.store.confirm_memory(memory.id)

        self.assertIsNotNone(confirmed.last_confirmed_at)
        self.assertTrue(confirmed.last_confirmed_at.endswith("+00:00"))
        self.assertEqual(confirmed.source_created_at, "2024-03-12T09:15:00+00:00")
        self.assertEqual(confirmed.source_conversation_id, "conversation-confirm")
        self.assertEqual(confirmed.source_message_id, 77)
        self.assertEqual(confirmed.evidence, "I currently work in construction.")
        self.assertEqual(confirmed.content, memory.content)
        self.assertEqual(confirmed.created_at, memory.created_at)

    def test_confirm_missing_memory_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.store.confirm_memory("missing-memory-id")

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