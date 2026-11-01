import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from v.desktop.memory_backfill_dialog import MemoryBackfillDialog


class MemoryBackfillDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = MemoryBackfillDialog()

    def tearDown(self):
        self.dialog.close()
        self.application.processEvents()

    @staticmethod
    def candidate(status="pending"):
        candidate_id = "a" * 32
        payload = {
            "source_message_id": 17,
            "source_conversation_id": "conversation-1",
            "source_created_at": "2026-10-31T10:00:00+00:00",
            "memory_type": "episodic",
            "subject": "Current work context",
            "content": "I currently work in construction.",
            "model_content": "The user currently works in construction.",
            "memory_key": "user.current_work_context",
            "provenance": "explicit",
            "confidence": 0.97,
            "importance": 4,
            "evidence": "I currently work in construction.",
        }
        return {
            "id": candidate_id,
            "status": status,
            "payload": payload,
            "review_note": None,
        }

    def test_window_has_native_controls_and_resize_grip(self):
        flags = self.dialog.windowFlags()
        for flag in (
            Qt.WindowType.WindowTitleHint,
            Qt.WindowType.WindowSystemMenuHint,
            Qt.WindowType.WindowCloseButtonHint,
            Qt.WindowType.WindowMinimizeButtonHint,
            Qt.WindowType.WindowMaximizeButtonHint,
        ):
            self.assertTrue(flags & flag)
        self.assertTrue(self.dialog.isSizeGripEnabled())

    def test_progress_displays_checkpoint_statistics(self):
        self.dialog.set_progress(
            {
                "status": "running",
                "total_messages": 40,
                "processed_messages": 10,
                "candidates_found": 7,
                "candidates_skipped": 3,
            }
        )
        self.assertEqual(self.dialog.progress_bar.value(), 25)
        self.assertIn("10 / 40 messages", self.dialog.progress_details.text())
        self.assertIn("7 proposals", self.dialog.progress_details.text())
        self.assertIn("Running", self.dialog.progress_status.text())
        self.assertTrue(self.dialog.pause_button.isEnabled())

    def test_candidate_selection_loads_evidence_and_editable_fields(self):
        self.dialog.set_candidates([self.candidate()])
        self.application.processEvents()

        self.assertEqual(self.dialog.candidate_table.rowCount(), 1)
        self.assertIn("17", self.dialog.candidate_id_label.text())
        self.assertIn(
            "2026-10-31T10:00:00+00:00",
            self.dialog.candidate_id_label.text(),
        )
        self.assertIn(
            "The user currently works in construction.",
            self.dialog.suggested_summary.text(),
        )
        self.assertEqual(
            self.dialog.evidence_text.toPlainText(),
            "I currently work in construction.",
        )
        self.assertEqual(
            self.dialog.content_input.toPlainText(),
            "I currently work in construction.",
        )
        self.assertEqual(
            self.dialog.memory_key_input.text(),
            "user.current_work_context",
        )
        self.assertTrue(self.dialog.approve_button.isEnabled())
        self.assertTrue(self.dialog.reject_button.isEnabled())

    def test_approval_emits_user_edited_candidate_fields(self):
        self.dialog.set_candidates([self.candidate()])
        self.application.processEvents()
        self.dialog.content_input.setPlainText(
            "The user currently works in construction."
        )
        self.dialog.importance_input.setValue(5)
        emitted = []
        self.dialog.approve_requested.connect(
            lambda candidate_id, changes: emitted.append((candidate_id, changes))
        )

        self.dialog._approve_selected()

        self.assertEqual(len(emitted), 1)
        candidate_id, changes = emitted[0]
        self.assertEqual(candidate_id, "a" * 32)
        self.assertEqual(
            changes["content"],
            "The user currently works in construction.",
        )
        self.assertEqual(changes["importance"], 5)
        self.assertTrue(self.dialog._review_pending)
        self.assertFalse(self.dialog.approve_button.isEnabled())

    def test_rejection_emits_reason_and_candidate_id(self):
        self.dialog.set_candidates([self.candidate()])
        self.application.processEvents()
        self.dialog.review_note_input.setText("Too temporary.")
        emitted = []
        self.dialog.reject_requested.connect(
            lambda candidate_id, reason: emitted.append((candidate_id, reason))
        )
        with patch(
            "v.desktop.memory_backfill_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.dialog._reject_selected()

        self.assertEqual(emitted, [("a" * 32, "Too temporary.")])
        self.assertTrue(self.dialog._review_pending)

    def test_start_and_pause_controls_emit_runtime_requests(self):
        starts = []
        pauses = []
        self.dialog.start_requested.connect(starts.append)
        self.dialog.pause_requested.connect(lambda: pauses.append(True))

        self.dialog.start_button.click()
        self.assertEqual(starts, [False])
        self.assertTrue(self.dialog._scan_running)

        self.dialog.pause_button.click()
        self.assertEqual(pauses, [True])

    def test_completed_candidates_are_read_only(self):
        self.dialog.set_candidates([self.candidate(status="approved")])
        self.application.processEvents()
        self.assertFalse(self.dialog.approve_button.isEnabled())
        self.assertFalse(self.dialog.reject_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
