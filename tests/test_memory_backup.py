import json
import unittest

from contextlib import closing
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
        self.assertEqual(payload["version"], 4)
        payload["version"] = 1
        payload.pop("evidence_links")
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

    def test_backup_round_trip_retains_multiple_episodic_snapshots_with_same_key(self):
        older = self.source.create_memory(
            content="The user worked at Site A.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2024-01-15T09:00:00+00:00",
        )
        newer = self.source.create_memory(
            content="The user works at Site B.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2026-10-30T09:00:00+00:00",
        )

        path, exported = export_backup(self.source, self.backup_path)
        restored, skipped = import_backup(self.target, path)

        self.assertEqual(exported, 2)
        self.assertEqual((restored, skipped), (2, 0))
        self.assertEqual(self.target.get_memory(older.id), older)
        self.assertEqual(self.target.get_memory(newer.id), newer)

    def test_backup_round_trip_preserves_inferred_pattern_evidence(self):
        sources = []
        for index, conversation_id in enumerate(
            ("conversation-a", "conversation-a", "conversation-b"),
            start=1,
        ):
            sources.append(
                self.source.create_memory(
                    content=f"Explicit source {index}.",
                    memory_type="preference",
                    subject="User",
                    source_conversation_id=conversation_id,
                    source_message_id=200 + index,
                    evidence=f"Original statement {index}.",
                )
            )
        pattern = self.source.create_inferred_pattern(
            content="The user repeatedly favors practical implementations.",
            subject="User",
            memory_key="pattern.practical",
            confidence=0.96,
            importance=4,
            evidence_memory_ids=[item.id for item in sources],
        )

        path, exported = export_backup(self.source, self.backup_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 4)
        self.assertEqual(len(payload["evidence_links"]), 3)

        restored, skipped = import_backup(self.target, path)
        self.assertEqual(exported, 4)
        self.assertEqual((restored, skipped), (4, 0))
        restored_pattern = self.target.get_memory(pattern.id)
        self.assertEqual(restored_pattern, pattern)
        self.assertEqual(
            {item.id for item in self.target.list_memory_evidence(pattern.id)},
            {item.id for item in sources},
        )

    def test_v2_backup_remains_importable(self):
        original = self.source.create_memory(content="A v2-compatible record.")
        export_backup(self.source, self.backup_path)
        payload = json.loads(self.backup_path.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload.pop("evidence_links")
        self.backup_path.write_text(json.dumps(payload), encoding="utf-8")

        self.assertEqual(import_backup(self.target, self.backup_path), (1, 0))
        self.assertEqual(self.target.get_memory(original.id), original)


    def test_v3_backup_remains_importable_without_continuity_records(self):
        original = self.source.create_memory(content="A v3-compatible record.")
        export_backup(self.source, self.backup_path)
        payload = json.loads(self.backup_path.read_text(encoding="utf-8"))
        payload["version"] = 3
        payload.pop("temporal_records")
        payload.pop("derivations")
        payload.pop("commitments")
        self.backup_path.write_text(json.dumps(payload), encoding="utf-8")

        self.assertEqual(import_backup(self.target, self.backup_path), (1, 0))
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


    def test_v4_backup_round_trip_preserves_continuity_records(self):
        from v.memory.continuity import ContinuityStore

        old = self.source.create_memory(content="The user used an older workflow.")
        current = self.source.create_memory(content="The user now uses a revised workflow.")
        summary = self.source.create_memory(
            content="The user's workflow changed over time.",
            memory_type="fact",
            provenance="inferred",
        )
        continuity = ContinuityStore(self.source.database_path)
        continuity.ensure_temporal_record(
            old.id,
            valid_from="2024-01-01T00:00:00+00:00",
            valid_until="2025-01-01T00:00:00+00:00",
        )
        continuity.set_memory_state(
            old.id,
            "superseded",
            superseded_by=current.id,
            note="A newer explicit record replaced this one.",
        )
        continuity.add_derivation(summary.id, [old.id, current.id])
        continuity.review_derivation(summary.id, "accepted")
        commitment = continuity.create_commitment(
            "Review the updated workflow",
            due_at="2026-11-10T12:00:00+07:00",
            source_memory_id=current.id,
        )

        path, exported = export_backup(self.source, self.backup_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 4)
        self.assertEqual(len(payload["temporal_records"]), 1)
        self.assertEqual(len(payload["derivations"]), 2)
        self.assertEqual(len(payload["commitments"]), 1)

        restored, skipped = import_backup(self.target, path)
        self.assertEqual((exported, restored, skipped), (3, 3, 0))
        target_continuity = ContinuityStore(self.target.database_path)
        with closing(self.target._connect()) as connection:
            temporal = connection.execute(
                "SELECT * FROM memory_temporal WHERE memory_id=?", (old.id,)
            ).fetchone()
            derivations = connection.execute(
                "SELECT state FROM memory_derivations WHERE derived_memory_id=?",
                (summary.id,),
            ).fetchall()
            restored_commitment = connection.execute(
                "SELECT * FROM memory_commitments WHERE id=?", (commitment["id"],)
            ).fetchone()
        self.assertEqual(temporal["state"], "superseded")
        self.assertEqual(temporal["superseded_by"], current.id)
        self.assertEqual({row["state"] for row in derivations}, {"accepted"})
        self.assertEqual(dict(restored_commitment), commitment)

        # A second import is idempotent across the continuity tables too.
        self.assertEqual(import_backup(self.target, path), (0, 3))

    def test_v4_backup_rejects_orphaned_continuity_references_atomically(self):
        from v.memory.continuity import ContinuityStore

        source = self.source.create_memory(content="Source memory.")
        derived = self.source.create_memory(content="Derived memory.")
        continuity = ContinuityStore(self.source.database_path)
        continuity.add_derivation(derived.id, [source.id])
        export_backup(self.source, self.backup_path)
        payload = json.loads(self.backup_path.read_text(encoding="utf-8"))
        payload["derivations"][0]["source_memory_id"] = "f" * 32
        self.backup_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "backed-up memories"):
            import_backup(self.target, self.backup_path)
        self.assertEqual(self.target.count_memories(), 0)



if __name__ == "__main__":
    unittest.main()
