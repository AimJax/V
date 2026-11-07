import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from v.desktop.memory_continuity_dialog import MemoryContinuityDialog


class MemoryContinuityDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = MemoryContinuityDialog("memory-selected")

    def tearDown(self):
        self.dialog.close()
        self.application.processEvents()

    def test_snapshot_displays_timeline_derivations_and_commitments(self):
        self.dialog.set_snapshot({
            "memory_id": "memory-selected",
            "temporal": {
                "state": "current",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "valid_until": None,
                "superseded_by": None,
                "note": "Current record.",
            },
            "timeline": [
                {
                    "memory_id": "memory-old",
                    "memory_type": "episodic",
                    "source_date": "2025-01-01T00:00:00+00:00",
                    "temporal_state": "superseded",
                    "content": "Earlier project state.",
                },
                {
                    "memory_id": "memory-selected",
                    "memory_type": "episodic",
                    "source_date": "2026-01-01T00:00:00+00:00",
                    "temporal_state": "current",
                    "content": "Current project state.",
                },
            ],
            "derivation_sources": [{
                "state": "pending",
                "memory_type": "preference",
                "subject": "User",
                "content": "The user prefers concise technical explanations.",
            }],
            "commitments": [{
                "id": "commitment-1",
                "title": "Review the project plan",
                "due_at": "2026-11-10T10:00:00+00:00",
                "state": "open",
                "source_memory_id": "memory-selected",
            }],
        })

        self.assertEqual(self.dialog.timeline_table.rowCount(), 2)
        self.assertEqual(
            self.dialog.timeline_table.item(1, 3).text(),
            "Current project state.",
        )
        self.assertEqual(self.dialog.derivation_list.count(), 1)
        self.assertTrue(self.dialog.accept_derivation_button.isEnabled())
        self.assertEqual(self.dialog.commitment_table.rowCount(), 1)
        self.assertIn("not scheduled reminders", self.dialog.status_label.text())


    def test_consolidation_status_distinguishes_duplicates_from_rejected_groups(self):
        from types import SimpleNamespace

        self.dialog.on_consolidation_completed(SimpleNamespace(
            summaries_created=1,
            duplicates_skipped=2,
            groups_skipped=3,
            failures=0,
        ))
        self.dialog.set_snapshot({
            "memory_id": "memory-selected",
            "temporal": {"state": "current"},
            "timeline": [],
            "derivation_sources": [],
            "commitments": [],
        })
        self.assertIn("2 duplicate(s)", self.dialog.status_label.text())
        self.assertIn("3 group(s) without a safe summary", self.dialog.status_label.text())

    def test_review_and_commitment_actions_emit_selected_ids(self):
        self.dialog.set_snapshot({
            "memory_id": "memory-selected",
            "temporal": {"state": "current"},
            "timeline": [],
            "derivation_sources": [{
                "state": "pending",
                "memory_type": "fact",
                "subject": "Project V",
                "content": "A source record.",
            }],
            "commitments": [{
                "id": "commitment-42",
                "title": "Run the tests",
                "due_at": None,
                "state": "open",
                "source_memory_id": "memory-selected",
            }],
        })
        derivations = []
        commitments = []
        self.dialog.derivation_review_requested.connect(
            lambda memory_id, decision: derivations.append((memory_id, decision))
        )
        self.dialog.commitment_update_requested.connect(
            lambda commitment_id, state, memory_id: commitments.append(
                (commitment_id, state, memory_id)
            )
        )

        self.dialog.accept_derivation_button.click()
        self.dialog.commitment_table.selectRow(0)
        self.dialog.complete_commitment_button.click()

        self.assertEqual(derivations, [("memory-selected", "accepted")])
        self.assertEqual(
            commitments,
            [("commitment-42", "completed", "memory-selected")],
        )


if __name__ == "__main__":
    unittest.main()
