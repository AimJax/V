import json
import unittest

from pathlib import Path

from support import temporary_directory

from v.memory.backup import export_backup, import_backup
from v.memory.store import MemoryStore


class MemoryBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        self.root = Path(self.temp_dir.name)
        self.source = MemoryStore(self.root / "source.sqlite3")
        self.target = MemoryStore(self.root / "target.sqlite3")
        self.backup_path = self.root / "exports" / "memories.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_and_restore_preserve_memory_records(self):
        original = self.source.create_memory(
            content="The user prefers one PowerShell step at a time.",
            memory_type="preference",
            subject="User",
            memory_key="workflow",
            provenance="explicit",
            confidence=1.0,
            importance=4,
            source_conversation_id="conversation-1",
            source_message_id=7,
            evidence="One step at a time.",
        )

        path, exported = export_backup(self.source, self.backup_path)
        restored, skipped = import_backup(self.target, path)
        copy = self.target.get_memory(original.id)

        self.assertEqual(exported, 1)
        self.assertEqual(restored, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(copy, original)
        self.assertEqual(
            len(self.target.search_memories("PowerShell")),
            1,
        )

    def test_v1_backup_imports_with_unknown_source_date(self):
        original = self.source.create_memory(
            content="A memory from an older backup.",
            source_conversation_id="conversation-legacy",
            source_message_id=18,
        )
        export_backup(self.source, self.backup_path)
        payload = json.loads(self.backup_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 2)
        payload["version"] = 1
        for record in payload["memories"]:
            record.pop("source_created_at")
        self.backup_path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        restored, skipped = import_backup(self.target, self.backup_path)
        copy = self.target.get_memory(original.id)

        self.assertEqual((restored, skipped), (1, 0))
        self.assertIsNone(copy.source_created_at)
        self.assertEqual(copy.source_message_id, 18)

    def test_import_is_idempotent_for_identical_ids(self):
        original = self.source.create_memory(content="A durable fact.")
        export_backup(self.source, self.backup_path)

        self.assertEqual(
            import_backup(self.target, self.backup_path),
            (1, 0),
        )
        self.assertEqual(
            import_backup(self.target, self.backup_path),
            (0, 1),
        )
        self.assertEqual(self.target.get_memory(original.id), original)

    def test_export_refuses_to_overwrite_without_explicit_flag(self):
        self.source.create_memory(content="Backup test.")
        export_backup(self.source, self.backup_path)

        with self.assertRaises(FileExistsError):
            export_backup(self.source, self.backup_path)

        export_backup(self.source, self.backup_path, overwrite=True)

    def test_unique_key_conflict_rolls_back_entire_import(self):
        self.source.create_memory(
            content="First record.",
            memory_key="first",
        )
        self.source.create_memory(
            content="Second record.",
            memory_key="occupied",
        )
        export_backup(self.source, self.backup_path)

        self.target.create_memory(
            content="Existing target record.",
            memory_key="occupied",
        )

        with self.assertRaisesRegex(ValueError, "Memory-key conflict"):
            import_backup(self.target, self.backup_path)

        self.assertEqual(self.target.count_memories(), 1)
        self.assertEqual(self.target.search_memories("First"), [])

    def test_invalid_backup_version_is_rejected(self):
        self.backup_path.parent.mkdir(parents=True)
        self.backup_path.write_text(
            json.dumps({
                "format": "v-memory-backup",
                "version": 999,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "memories": [],
            }),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "Unsupported memory backup version"):
            import_backup(self.target, self.backup_path)


if __name__ == "__main__":
    unittest.main()
