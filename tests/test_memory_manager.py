import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from v.desktop.memory_manager import MemoryManagerDialog
from v.memory.models import Memory


class MemoryManagerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = MemoryManagerDialog()

    def test_window_has_native_controls_and_fits_available_screen(self):
        flags = self.dialog.windowFlags()
        for flag in (
            Qt.WindowType.WindowTitleHint,
            Qt.WindowType.WindowSystemMenuHint,
            Qt.WindowType.WindowCloseButtonHint,
            Qt.WindowType.WindowMinimizeButtonHint,
            Qt.WindowType.WindowMaximizeButtonHint,
        ):
            self.assertTrue(flags & flag)

        self.assertTrue(self.dialog.sizeGripEnabled())
        screen = self.dialog.screen()
        if screen is not None:
            available = screen.availableGeometry()
            self.assertLessEqual(self.dialog.width(), available.width())
            self.assertLessEqual(self.dialog.height(), available.height())
            self.assertLessEqual(self.dialog.minimumWidth(), available.width())
            self.assertLessEqual(self.dialog.minimumHeight(), available.height())

    def tearDown(self):
        self.dialog._dirty = False
        self.dialog.close()
        self.application.processEvents()

    def _memory(self):
        return Memory(
            id="a" * 32,
            memory_type="preference",
            subject="User",
            content="The user prefers one PowerShell step at a time.",
            memory_key="workflow",
            provenance="explicit",
            confidence=1.0,
            importance=4,
            source_conversation_id="conversation-1",
            source_message_id=9,
            evidence="one PowerShell step at a time",
            created_at="2026-10-31T10:00:00+00:00",
            updated_at="2026-10-31T10:01:00+00:00",
            last_confirmed_at="2026-10-31T10:00:00+00:00",
        )

    def test_memory_records_and_provenance_are_displayed(self):
        memory = self._memory()
        self.dialog.set_memories([memory])
        self.application.processEvents()

        self.assertEqual(self.dialog.memory_table.rowCount(), 1)
        self.assertIn(memory.id, self.dialog.memory_id_label.text())
        self.assertEqual(self.dialog.content_input.toPlainText(), memory.content)
        self.assertIn("explicit", self.dialog.provenance_label.text())
        self.assertIn("message 9", self.dialog.source_label.text())
        self.assertTrue(self.dialog.save_button.isEnabled())
        self.assertTrue(self.dialog.delete_button.isEnabled())

    def test_empty_result_disables_memory_editor(self):
        self.dialog.set_memories([])
        self.application.processEvents()

        self.assertEqual(self.dialog.memory_table.rowCount(), 0)
        self.assertFalse(self.dialog.save_button.isEnabled())
        self.assertFalse(self.dialog.delete_button.isEnabled())
        self.assertEqual(self.dialog.memory_id_label.text(), "No memory selected")

    def test_search_and_filter_values_are_emitted(self):
        emitted = []
        self.dialog.refresh_requested.connect(
            lambda query, memory_type, provenance: emitted.append(
                (query, memory_type, provenance)
            )
        )
        self.dialog.search_input.setText("PowerShell steps")
        self.dialog.type_filter.setCurrentIndex(
            self.dialog.type_filter.findData("preference")
        )
        self.dialog.provenance_filter.setCurrentIndex(
            self.dialog.provenance_filter.findData("explicit")
        )

        self.dialog.refresh()

        self.assertEqual(
            emitted,
            [("PowerShell steps", "preference", "explicit")],
        )

    def test_save_emits_only_editable_memory_fields(self):
        memory = self._memory()
        self.dialog.set_memories([memory])
        self.application.processEvents()

        emitted = []
        self.dialog.update_requested.connect(
            lambda memory_id, changes: emitted.append((memory_id, changes))
        )
        self.dialog.content_input.setPlainText(
            "The user wants verified PowerShell steps."
        )
        self.dialog.importance_input.setValue(5)
        self.dialog._save()

        self.assertEqual(len(emitted), 1)
        memory_id, changes = emitted[0]
        self.assertEqual(memory_id, memory.id)
        self.assertEqual(
            changes["content"],
            "The user wants verified PowerShell steps.",
        )
        self.assertEqual(changes["importance"], 5)
        self.assertEqual(changes["provenance"] if "provenance" in changes else None, None)
        self.assertNotIn("source_message_id", changes)

    def test_modified_record_is_marked_unsaved(self):
        self.dialog.set_memories([self._memory()])
        self.dialog.content_input.setPlainText("Corrected content")

        self.assertTrue(self.dialog._dirty)
        self.assertEqual(self.dialog.dirty_label.text(), "Unsaved changes")


if __name__ == "__main__":
    unittest.main()
