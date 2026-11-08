import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from support import temporary_directory
from v.cognition import CognitiveStore
from v.desktop.cognitive_manager import CognitiveManagerDialog


class CognitiveManagerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_candidate_and_preference_review_are_exposed(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            store.propose_goal(
                "Explore procedural generation",
                evidence_refs=("conversation:1", "conversation:2"),
                rationale="Repeated project interest.",
            )
            store.propose_preference(
                "Prefers concise technical explanations.",
                evidence_refs=("conversation:3", "conversation:4"),
                confidence=0.9,
                rationale="Repeated explicit requests.",
            )
            dialog = CognitiveManagerDialog(store)
            self.application.processEvents()
            self.assertEqual(dialog.goal_proposals.count(), 1)
            self.assertEqual(dialog.preferences.count(), 1)
            dialog.goal_proposals.setCurrentRow(0)
            dialog._review_goal_proposal(True)
            self.application.processEvents()
            self.assertEqual(store.list_goal_proposals(status="pending"), [])
            self.assertEqual(store.list_goals(status="active")[0].origin, "v_candidate")
            dialog.close()
            dialog.deleteLater()
            self.application.processEvents()

    def test_empty_sections_explain_that_there_are_no_records(self):
        with temporary_directory() as temp:
            dialog = CognitiveManagerDialog(
                CognitiveStore(Path(temp) / "cognition.sqlite3")
            )
            self.assertIn("No goals yet", dialog.goals.item(0).text())
            self.assertIn("No pending goal candidates", dialog.goal_proposals.item(0).text())
            self.assertIn("No pending preferences", dialog.preferences.item(0).text())
            dialog.close()
            dialog.deleteLater()
            self.application.processEvents()

    def test_dialog_exposes_native_minimize_maximize_and_close_controls(self):
        with temporary_directory() as temp:
            dialog = CognitiveManagerDialog(
                CognitiveStore(Path(temp) / "cognition.sqlite3")
            )
            flags = dialog.windowFlags()
            self.assertTrue(flags & Qt.WindowType.WindowMinimizeButtonHint)
            self.assertTrue(flags & Qt.WindowType.WindowMaximizeButtonHint)
            self.assertTrue(flags & Qt.WindowType.WindowCloseButtonHint)
            dialog.close()
            dialog.deleteLater()
            self.application.processEvents()

    def test_dialog_has_resizable_window_bounds(self):
        with temporary_directory() as temp:
            dialog = CognitiveManagerDialog(
                CognitiveStore(Path(temp) / "cognition.sqlite3")
            )
            self.assertGreaterEqual(dialog.minimumWidth(), 600)
            self.assertGreaterEqual(dialog.minimumHeight(), 600)
            self.assertGreaterEqual(dialog.width(), dialog.minimumWidth())
            self.assertGreaterEqual(dialog.height(), dialog.minimumHeight())
            dialog.close()
            dialog.deleteLater()
            self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
