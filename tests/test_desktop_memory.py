import unittest

from pathlib import Path

from support import temporary_directory

from v.desktop.service import DesktopService
from v.memory.continuity import ContinuityStore
from v.memory.store import MemoryStore


class DesktopServiceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        self.root = Path(self.temp_dir.name)
        self.service = DesktopService()
        self.store = MemoryStore(self.root / "memory.sqlite3")
        self.service.memory_store = self.store

        self.preference = self.store.create_memory(
            content="The user prefers PowerShell instructions one step at a time.",
            memory_type="preference",
            subject="User",
            memory_key="workflow",
            provenance="explicit",
            confidence=1.0,
            importance=4,
            source_conversation_id="conversation-1",
            source_message_id=9,
            evidence="one step at a time",
        )
        self.fact = self.store.create_memory(
            content="V is a local AI companion project.",
            memory_type="project",
            subject="V",
            provenance="inferred",
            confidence=0.75,
            importance=3,
        )

    def tearDown(self):
        self.temp_dir.cleanup()


    def test_continuity_snapshot_includes_subject_timeline(self):
        self.service.continuity_store = ContinuityStore(self.store.database_path)
        related = self.store.create_memory(
            content="The user is working on a local companion project.",
            memory_type="episodic",
            subject="User",
            provenance="explicit",
            source_conversation_id="conversation-2",
            source_message_id=10,
            source_created_at="2026-11-06T10:00:00+00:00",
            evidence="working on a local companion project",
        )
        self.service.continuity_store.set_memory_state(
            related.id, "disputed", note="Needs confirmation."
        )

        snapshot = self.service.memory_continuity_snapshot(self.preference.id)

        timeline_ids = {item["memory_id"] for item in snapshot["timeline"]}
        self.assertIn(self.preference.id, timeline_ids)
        self.assertIn(related.id, timeline_ids)
        related_timeline = next(
            item for item in snapshot["timeline"]
            if item["memory_id"] == related.id
        )
        self.assertEqual(related_timeline["temporal_state"], "disputed")

    def test_memory_search_and_filters(self):
        results = self.service.list_memories(
            query="PowerShell",
            memory_type="preference",
            provenance="explicit",
        )

        self.assertEqual([item.id for item in results], [self.preference.id])

    def test_memory_filters_can_return_all_records(self):
        results = self.service.list_memories()
        self.assertEqual({item.id for item in results}, {
            self.preference.id,
            self.fact.id,
        })

    def test_memory_update_preserves_source_references(self):
        updated = self.service.update_memory(
            self.preference.id,
            {
                "content": "The user wants one verified PowerShell step at a time.",
                "importance": 5,
            },
        )

        self.assertEqual(updated.importance, 5)
        self.assertEqual(updated.source_conversation_id, "conversation-1")
        self.assertEqual(updated.source_message_id, 9)
        self.assertEqual(updated.evidence, "one step at a time")
        self.assertEqual(updated.created_at, self.preference.created_at)

    def test_memory_confirmation_preserves_original_source(self):
        confirmed = self.service.confirm_memory(self.preference.id)

        self.assertIsNotNone(confirmed.last_confirmed_at)
        self.assertEqual(confirmed.source_created_at, self.preference.source_created_at)
        self.assertEqual(confirmed.source_conversation_id, "conversation-1")
        self.assertEqual(confirmed.source_message_id, 9)
        self.assertEqual(confirmed.evidence, "one step at a time")
        self.assertEqual(confirmed.content, self.preference.content)

    def test_memory_delete_removes_record(self):
        self.assertTrue(self.service.delete_memory(self.fact.id))
        self.assertIsNone(self.store.get_memory(self.fact.id))

    def test_export_and_import_use_merge_restore(self):
        backup = self.root / "memories.json"
        message = self.service.export_memories(str(backup))
        self.assertIn("unencrypted", message)

        target = MemoryStore(self.root / "target.sqlite3")
        self.service.memory_store = target
        result = self.service.import_memories(str(backup))

        self.assertIn("Restored 2 record(s)", result)
        self.assertEqual(target.count_memories(), 2)


if __name__ == "__main__":
    unittest.main()
