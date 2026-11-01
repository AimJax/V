"""Local, editable management window for V's long-term memories."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from v.memory.models import Memory


MEMORY_TYPES = (
    "profile",
    "preference",
    "episodic",
    "relationship",
    "project",
    "fact",
    "inferred_pattern",
)


class MemoryManagerDialog(QDialog):
    """Inspect, search, correct, delete, and back up local memory records."""

    refresh_requested = Signal(str, str, str)
    update_requested = Signal(str, object)
    delete_requested = Signal(str)
    export_requested = Signal(str, bool)
    import_requested = Signal(str)
    backfill_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._memories: list[Memory] = []
        self._selected_memory_id: str | None = None
        self._selected_row = -1
        self._dirty = False
        self._loading = False
        self._operation_pending = False

        self.setWindowTitle("V — Memory Manager")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.setModal(False)
        self._fit_to_available_screen()

        self._build_ui()
        self._connect_editor_signals()
        self._set_editor_enabled(False)

    def _fit_to_available_screen(self) -> None:
        """Keep the full native title bar and window controls on-screen."""
        screen = self.screen()
        if screen is None:
            self.setMinimumSize(900, 620)
            self.resize(1120, 760)
            return

        available = screen.availableGeometry()
        width = min(1120, max(1, int(available.width() * 0.92)))
        height = min(760, max(1, int(available.height() * 0.92)))
        self.setMinimumSize(min(900, width), min(620, height))
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        heading = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("Memory Manager")
        title.setStyleSheet("font-size: 18pt; font-weight: 650;")
        subtitle = QLabel(
            "Inspect and correct what V remembers. All records remain on this PC."
        )
        subtitle.setObjectName("muted")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)

        self.status_label = QLabel("Loading memories…")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumWidth(440)
        heading.addLayout(title_column)
        heading.addStretch(1)
        heading.addWidget(self.status_label)
        root.addLayout(heading)

        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search memory content or subject…")
        self.search_input.returnPressed.connect(self.refresh)
        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", "")
        for memory_type in MEMORY_TYPES:
            self.type_filter.addItem(memory_type.replace("_", " ").title(), memory_type)

        self.provenance_filter = QComboBox()
        self.provenance_filter.addItem("All sources", "")
        self.provenance_filter.addItem("Explicit", "explicit")
        self.provenance_filter.addItem("Inferred", "inferred")

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.refresh)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.provenance_filter)
        filters.addWidget(self.search_button)
        filters.addWidget(self.refresh_button)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.memory_table = QTableWidget(0, 5)
        self.memory_table.setHorizontalHeaderLabels(
            ["Type", "Subject", "Content", "Origin", "Priority"]
        )
        self.memory_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.memory_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.memory_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.memory_table.setAlternatingRowColors(True)
        self.memory_table.setWordWrap(False)
        self.memory_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        header = self.memory_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.memory_table.verticalHeader().setVisible(False)
        self.memory_table.currentCellChanged.connect(
            self._on_current_cell_changed
        )
        splitter.addWidget(self.memory_table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(9)

        details_title = QLabel("Selected memory")
        details_title.setStyleSheet("font-size: 12pt; font-weight: 650;")
        detail_layout.addWidget(details_title)

        self.memory_id_label = QLabel("No memory selected")
        self.memory_id_label.setObjectName("muted")
        self.memory_id_label.setWordWrap(True)
        detail_layout.addWidget(self.memory_id_label)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.memory_type = QComboBox()
        for value in MEMORY_TYPES:
            self.memory_type.addItem(value.replace("_", " ").title(), value)

        self.subject_input = QLineEdit()
        self.content_input = QTextEdit()
        self.content_input.setMinimumHeight(105)
        self.content_input.setMaximumHeight(170)
        self.content_input.setPlaceholderText("Stored memory content")

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("Optional unique key")

        self.confidence_input = QDoubleSpinBox()
        self.confidence_input.setRange(0.0, 1.0)
        self.confidence_input.setDecimals(2)
        self.confidence_input.setSingleStep(0.05)

        self.importance_input = QSpinBox()
        self.importance_input.setRange(1, 5)

        self.evidence_input = QTextEdit()
        self.evidence_input.setMinimumHeight(75)
        self.evidence_input.setMaximumHeight(120)
        self.evidence_input.setPlaceholderText("Original supporting quotation")

        form.addRow("Type", self.memory_type)
        form.addRow("Subject", self.subject_input)
        form.addRow("Content", self.content_input)
        form.addRow("Memory key", self.key_input)
        form.addRow("Confidence", self.confidence_input)
        form.addRow("Importance", self.importance_input)
        form.addRow("Evidence", self.evidence_input)
        detail_layout.addLayout(form)

        metadata_title = QLabel("Provenance and history")
        metadata_title.setStyleSheet("font-weight: 650;")
        detail_layout.addWidget(metadata_title)

        self.provenance_label = QLabel("Source: —")
        self.source_label = QLabel("Source reference: —")
        self.created_label = QLabel("Created: —")
        self.updated_label = QLabel("Updated: —")
        self.confirmed_label = QLabel("Last confirmed: —")
        for label in (
            self.provenance_label,
            self.source_label,
            self.created_label,
            self.updated_label,
            self.confirmed_label,
        ):
            label.setObjectName("muted")
            label.setWordWrap(True)
            detail_layout.addWidget(label)

        self.dirty_label = QLabel("No unsaved changes")
        self.dirty_label.setObjectName("muted")
        detail_layout.addStretch(1)
        detail_layout.addWidget(self.dirty_label)

        splitter.addWidget(detail)
        splitter.setSizes([520, 560])
        root.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.backfill_button = QPushButton("Reprocess history…")
        self.export_button = QPushButton("Export…")
        self.import_button = QPushButton("Import…")
        self.delete_button = QPushButton("Delete")
        self.backfill_button.clicked.connect(self.backfill_requested.emit)
        self.save_button = QPushButton("Save changes")
        self.save_button.setObjectName("primary")

        self.export_button.clicked.connect(self._export)
        self.import_button.clicked.connect(self._import)
        self.delete_button.clicked.connect(self._delete)
        self.save_button.clicked.connect(self._save)

        actions.addWidget(self.backfill_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.import_button)
        actions.addStretch(1)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.save_button)
        root.addLayout(actions)

    def _connect_editor_signals(self) -> None:
        self.memory_type.currentIndexChanged.connect(self._mark_dirty)
        self.subject_input.textChanged.connect(self._mark_dirty)
        self.content_input.textChanged.connect(self._mark_dirty)
        self.key_input.textChanged.connect(self._mark_dirty)
        self.confidence_input.valueChanged.connect(self._mark_dirty)
        self.importance_input.valueChanged.connect(self._mark_dirty)
        self.evidence_input.textChanged.connect(self._mark_dirty)

    def _set_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self.memory_type,
            self.subject_input,
            self.content_input,
            self.key_input,
            self.confidence_input,
            self.importance_input,
            self.evidence_input,
            self.save_button,
            self.delete_button,
        ):
            widget.setEnabled(enabled and not self._operation_pending)

    def _mark_dirty(self, *_args) -> None:
        if self._loading or self._selected_memory_id is None:
            return
        self._dirty = True
        self.dirty_label.setText("Unsaved changes")
        self.save_button.setEnabled(not self._operation_pending)
    
    def refresh(self) -> None:
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Discard changes?",
                "You have unsaved memory corrections. Discard them and refresh?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
            self._dirty = False

        self._operation_pending = True
        self._update_action_state()
        self.status_label.setText("Loading memories…")
        self.refresh_requested.emit(
            self.search_input.text().strip(),
            str(self.type_filter.currentData() or ""),
            str(self.provenance_filter.currentData() or ""),
        )

    def set_memories(self, memories: list[Memory]) -> None:
        previous_id = self._selected_memory_id
        self._memories = list(memories)
        self._operation_pending = False
        self._dirty = False

        blocker = QSignalBlocker(self.memory_table)
        self.memory_table.setRowCount(len(self._memories))
        selected_row = -1

        for row, memory in enumerate(self._memories):
            values = (
                memory.memory_type.replace("_", " ").title(),
                memory.subject,
                memory.content,
                memory.provenance.title(),
                str(memory.importance),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, memory.id)
                self.memory_table.setItem(row, column, item)

            self.memory_table.setRowHeight(row, 34)
            if memory.id == previous_id:
                selected_row = row

        if selected_row < 0 and self._memories:
            selected_row = 0

        if selected_row >= 0:
            self.memory_table.setCurrentCell(selected_row, 0)
            self.memory_table.selectRow(selected_row)
        else:
            self.memory_table.clearSelection()
            self.memory_table.setCurrentCell(-1, -1)

        del blocker

        if selected_row >= 0:
            self._load_memory(self._memories[selected_row])
        else:
            self._selected_memory_id = None
            self._selected_row = -1
            self._clear_editor()

        self.status_label.setText(
            f"{len(self._memories)} memory record(s)"
        )
        self._update_action_state()

    def _on_current_cell_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if current_row < 0 or current_row >= len(self._memories):
            return

        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Discard changes?",
                "You have unsaved corrections. Discard them and select another memory?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                blocker = QSignalBlocker(self.memory_table)
                if self._selected_row >= 0:
                    self.memory_table.selectRow(self._selected_row)
                    self.memory_table.setCurrentCell(self._selected_row, 0)
                del blocker
                return

        self._load_memory(self._memories[current_row])

    def _load_memory(self, memory: Memory) -> None:
        self._loading = True
        self._selected_memory_id = memory.id
        self._selected_row = self._memories.index(memory)

        self.memory_id_label.setText(f"ID: {memory.id}")
        self.memory_type.setCurrentIndex(
            max(0, self.memory_type.findData(memory.memory_type))
        )
        self.subject_input.setText(memory.subject)
        self.content_input.setPlainText(memory.content)
        self.key_input.setText(memory.memory_key or "")
        self.confidence_input.setValue(memory.confidence)
        self.importance_input.setValue(memory.importance)
        self.evidence_input.setPlainText(memory.evidence or "")

        self.provenance_label.setText(
            f"Provenance: {memory.provenance} (read-only)"
        )
        source_reference = (
            f"conversation {memory.source_conversation_id}, "
            f"message {memory.source_message_id}"
            if memory.source_conversation_id is not None
            or memory.source_message_id is not None
            else "not recorded"
        )
        source_date = memory.source_created_at or "unknown"
        self.source_label.setText(
            f"Source reference: {source_reference} · Original message date: {source_date}"
        )
        self.created_label.setText(f"Created: {memory.created_at}")
        self.updated_label.setText(f"Updated: {memory.updated_at}")
        self.confirmed_label.setText(
            f"Last confirmed: {memory.last_confirmed_at or 'not confirmed'}"
        )

        self._loading = False
        self._dirty = False
        self.dirty_label.setText("No unsaved changes")
        self._set_editor_enabled(True)

    def _clear_editor(self) -> None:
        self._loading = True
        self.memory_id_label.setText("No memory selected")
        self.memory_type.setCurrentIndex(0)
        self.subject_input.clear()
        self.content_input.clear()
        self.key_input.clear()
        self.confidence_input.setValue(0.0)
        self.importance_input.setValue(3)
        self.evidence_input.clear()
        self.provenance_label.setText("Provenance: —")
        self.source_label.setText("Source reference: —")
        self.created_label.setText("Created: —")
        self.updated_label.setText("Updated: —")
        self.confirmed_label.setText("Last confirmed: —")
        self._loading = False
        self._dirty = False
        self.dirty_label.setText("No unsaved changes")
        self._set_editor_enabled(False)

    def _save(self) -> None:
        if self._selected_memory_id is None or self._operation_pending:
            return

        content = self.content_input.toPlainText().strip()
        if not content:
            QMessageBox.warning(
                self,
                "Content required",
                "A memory cannot have empty content.",
            )
            return

        changes = {
            "memory_type": str(self.memory_type.currentData()),
            "subject": self.subject_input.text().strip(),
            "content": content,
            "memory_key": self.key_input.text().strip() or None,
            "confidence": self.confidence_input.value(),
            "importance": self.importance_input.value(),
            "evidence": self.evidence_input.toPlainText().strip() or None,
        }

        self._operation_pending = True
        self._update_action_state()
        self.status_label.setText("Saving correction…")
        self.update_requested.emit(self._selected_memory_id, changes)

    def on_memory_updated(self, memory: Memory) -> None:
        self._selected_memory_id = memory.id
        self._dirty = False
        self.status_label.setText("Memory correction saved.")
        self.refresh()

    def _delete(self) -> None:
        if self._selected_memory_id is None or self._operation_pending:
            return

        answer = QMessageBox.question(
            self,
            "Permanently delete memory?",
            "This permanently deletes the selected memory from V's memory database. "
            "It does not remove copies from conversation history or backups.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._operation_pending = True
        self._update_action_state()
        self.status_label.setText("Deleting memory…")
        self.delete_requested.emit(self._selected_memory_id)

    def on_memory_deleted(self, memory_id: str) -> None:
        self._selected_memory_id = None
        self._dirty = False
        self.status_label.setText(f"Deleted memory {memory_id}.")
        self.refresh()

    def _export(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export V memories",
            str(Path.home() / "memories.json"),
            "JSON backups (*.json)",
        )
        if not path:
            return

        privacy = QMessageBox.warning(
            self,
            "Unencrypted memory backup",
            "V memory backups are plaintext JSON and may contain personal information. "
            "Save the file only in a location you control.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if privacy != QMessageBox.StandardButton.Ok:
            return

        overwrite = False
        if Path(path).exists():
            answer = QMessageBox.question(
                self,
                "Replace existing backup?",
                "The selected file already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True

        self._operation_pending = True
        self._update_action_state()
        self.status_label.setText("Exporting memories…")
        self.export_requested.emit(path, overwrite)

    def _import(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import V memory backup",
            str(Path.home()),
            "JSON backups (*.json)",
        )
        if not path:
            return

        answer = QMessageBox.warning(
            self,
            "Merge memory backup?",
            "Import validates the backup and merges its records. Identical records "
            "are skipped. Conflicts abort the entire import. Existing memories are "
            "never overwritten or deleted.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return

        if self._dirty:
            discard = QMessageBox.question(
                self,
                "Discard unsaved corrections?",
                "Importing will refresh the memory list. Discard your unsaved corrections?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if discard != QMessageBox.StandardButton.Discard:
                return
            self._dirty = False
            self.dirty_label.setText("No unsaved changes")

        self._operation_pending = True
        self._update_action_state()
        self.status_label.setText("Importing memory backup…")
        self.import_requested.emit(path)

    def on_backup_completed(self, message: str) -> None:
        self._operation_pending = False
        self.status_label.setText(message)
        self._update_action_state()

    def on_operation_failed(self, message: str) -> None:
        self._operation_pending = False
        self.status_label.setText("Memory operation failed.")
        self._update_action_state()
        QMessageBox.warning(self, "Memory operation failed", message)

    def _update_action_state(self) -> None:
        enabled = not self._operation_pending
        self.search_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)
        self.search_input.setEnabled(enabled)
        self.type_filter.setEnabled(enabled)
        self.provenance_filter.setEnabled(enabled)
        self.backfill_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self._set_editor_enabled(self._selected_memory_id is not None)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Discard changes?",
                "Close Memory Manager and discard unsaved corrections?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        event.accept()
