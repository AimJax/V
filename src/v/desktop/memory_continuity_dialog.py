"""Inspection and editing controls for temporal memory continuity."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class MemoryContinuityDialog(QDialog):
    """Inspect temporal state, evidence derivations, and future commitments."""

    refresh_requested = Signal(str)
    temporal_update_requested = Signal(str, str, str, str, str, str)
    derivation_review_requested = Signal(str, str)
    commitment_create_requested = Signal(str, str, str, str)
    commitment_update_requested = Signal(str, str, str)
    consolidation_requested = Signal()
    consolidation_cancel_requested = Signal()

    def __init__(self, memory_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.memory_id = memory_id
        self._snapshot: dict = {}
        self.setWindowTitle("V — Memory Continuity")
        self.resize(820, 700)
        self.setMinimumSize(680, 560)

        root = QVBoxLayout(self)
        heading = QLabel("Memory continuity")
        heading.setStyleSheet("font-size: 17pt; font-weight: 650;")
        self.memory_label = QLabel(f"Selected memory: {memory_id}")
        self.memory_label.setWordWrap(True)
        self.status_label = QLabel("Loading continuity records…")
        self.status_label.setWordWrap(True)
        root.addWidget(heading)
        root.addWidget(self.memory_label)
        root.addWidget(self.status_label)

        temporal_form = QFormLayout()
        self.state_combo = QComboBox()
        for value in ("current", "superseded", "corrected", "disputed", "expired"):
            self.state_combo.addItem(value.replace("_", " ").title(), value)
        self.replacement_input = QLineEdit()
        self.replacement_input.setPlaceholderText("Required only when superseded")
        self.valid_from_input = QLineEdit()
        self.valid_from_input.setPlaceholderText("Optional ISO-8601 timestamp with timezone")
        self.valid_until_input = QLineEdit()
        self.valid_until_input.setPlaceholderText("Optional ISO-8601 timestamp with timezone")
        self.note_input = QTextEdit()
        self.note_input.setMaximumHeight(72)
        temporal_form.addRow("Lifecycle", self.state_combo)
        temporal_form.addRow("Replacement memory ID", self.replacement_input)
        temporal_form.addRow("Valid from", self.valid_from_input)
        temporal_form.addRow("Valid until", self.valid_until_input)
        temporal_form.addRow("Review note", self.note_input)
        root.addLayout(temporal_form)

        temporal_actions = QHBoxLayout()
        self.save_temporal_button = QPushButton("Save temporal state")
        self.consolidate_button = QPushButton("Generate local summary proposals")
        self.cancel_consolidation_button = QPushButton("Cancel")
        self.refresh_button = QPushButton("Refresh")
        self.save_temporal_button.clicked.connect(self._save_temporal)
        self.consolidate_button.clicked.connect(self._start_consolidation)
        self.cancel_consolidation_button.clicked.connect(
            self.consolidation_cancel_requested.emit
        )
        self.refresh_button.clicked.connect(self.refresh)
        temporal_actions.addWidget(self.save_temporal_button)
        temporal_actions.addWidget(self.consolidate_button)
        temporal_actions.addWidget(self.cancel_consolidation_button)
        temporal_actions.addStretch(1)
        temporal_actions.addWidget(self.refresh_button)
        root.addLayout(temporal_actions)

        divider = QLabel("Derived memory evidence")
        divider.setStyleSheet("font-weight: 650; margin-top: 8px;")
        root.addWidget(divider)
        self.derivation_list = QListWidget()
        self.derivation_list.setMinimumHeight(90)
        root.addWidget(self.derivation_list)
        derivation_actions = QHBoxLayout()
        self.accept_derivation_button = QPushButton("Accept derivation")
        self.reject_derivation_button = QPushButton("Reject derivation")
        self.accept_derivation_button.clicked.connect(
            lambda: self._review_derivation("accepted")
        )
        self.reject_derivation_button.clicked.connect(
            lambda: self._review_derivation("rejected")
        )
        derivation_actions.addWidget(self.accept_derivation_button)
        derivation_actions.addWidget(self.reject_derivation_button)
        derivation_actions.addStretch(1)
        root.addLayout(derivation_actions)

        commitments_title = QLabel("Prospective commitments")
        commitments_title.setStyleSheet("font-weight: 650; margin-top: 8px;")
        root.addWidget(commitments_title)
        self.commitment_table = QTableWidget(0, 3)
        self.commitment_table.setHorizontalHeaderLabels(["Title", "Due", "State"])
        self.commitment_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.commitment_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.commitment_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.commitment_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.commitment_table, 1)

        create_form = QFormLayout()
        self.commitment_title_input = QLineEdit()
        self.commitment_title_input.setPlaceholderText("New commitment")
        self.commitment_due_input = QLineEdit()
        self.commitment_due_input.setPlaceholderText("Optional ISO-8601 due time with timezone")
        self.commitment_description_input = QLineEdit()
        self.commitment_description_input.setPlaceholderText("Optional context")
        create_form.addRow("Title", self.commitment_title_input)
        create_form.addRow("Due", self.commitment_due_input)
        create_form.addRow("Description", self.commitment_description_input)
        root.addLayout(create_form)

        commitment_actions = QHBoxLayout()
        self.add_commitment_button = QPushButton("Add commitment")
        self.complete_commitment_button = QPushButton("Mark completed")
        self.cancel_commitment_button = QPushButton("Cancel commitment")
        self.add_commitment_button.clicked.connect(self._create_commitment)
        self.complete_commitment_button.clicked.connect(
            lambda: self._update_commitment("completed")
        )
        self.cancel_commitment_button.clicked.connect(
            lambda: self._update_commitment("cancelled")
        )
        commitment_actions.addWidget(self.add_commitment_button)
        commitment_actions.addStretch(1)
        commitment_actions.addWidget(self.complete_commitment_button)
        commitment_actions.addWidget(self.cancel_commitment_button)
        root.addLayout(commitment_actions)

        self.refresh()

    def refresh(self) -> None:
        self.status_label.setText("Loading continuity records…")
        self.refresh_requested.emit(self.memory_id)

    def set_snapshot(self, snapshot: dict) -> None:
        if snapshot.get("memory_id") != self.memory_id:
            return
        self._snapshot = snapshot
        temporal = snapshot.get("temporal", {})
        index = self.state_combo.findData(temporal.get("state", "current"))
        self.state_combo.setCurrentIndex(max(0, index))
        self.replacement_input.setText(temporal.get("superseded_by") or "")
        self.valid_from_input.setText(temporal.get("valid_from") or "")
        self.valid_until_input.setText(temporal.get("valid_until") or "")
        self.note_input.setPlainText(temporal.get("note") or "")

        self.derivation_list.clear()
        sources = snapshot.get("derivation_sources", [])
        for source in sources:
            self.derivation_list.addItem(
                f"{source['state']} · {source['memory_type']} · "
                f"{source['subject']}: {source['content'][:180]}"
            )
        has_pending = any(item["state"] == "pending" for item in sources)
        self.accept_derivation_button.setEnabled(has_pending)
        self.reject_derivation_button.setEnabled(has_pending)

        commitments = snapshot.get("commitments", [])
        self.commitment_table.setRowCount(len(commitments))
        for row, item in enumerate(commitments):
            values = (item["title"], item.get("due_at") or "No due time", item["state"])
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                self.commitment_table.setItem(row, column, cell)
        self.status_label.setText(
            f"{len(sources)} derivation source(s) · "
            f"{len(commitments)} commitment(s). Due dates are records, not scheduled reminders."
        )

    def _start_consolidation(self) -> None:
        self.status_label.setText(
            "Preparing local summary proposals. New summaries remain pending review."
        )
        self.consolidation_requested.emit()

    def on_consolidation_completed(self, report) -> None:
        self.status_label.setText(
            f"Consolidation finished: {report.summaries_created} proposal(s), "
            f"{report.duplicates_skipped} skipped, {report.failures} failure(s). "
            "New proposals require explicit review."
        )
        self.refresh()

    def _save_temporal(self) -> None:
        state = str(self.state_combo.currentData())
        replacement = self.replacement_input.text().strip()
        if state == "superseded" and not replacement:
            QMessageBox.warning(
                self, "Replacement required",
                "A superseded memory must identify its replacement memory ID.",
            )
            return
        if state != "superseded" and replacement:
            QMessageBox.warning(
                self, "Replacement not applicable",
                "Clear the replacement ID unless the state is Superseded.",
            )
            return
        self.temporal_update_requested.emit(
            self.memory_id,
            state,
            replacement,
            self.note_input.toPlainText().strip(),
            self.valid_from_input.text().strip(),
            self.valid_until_input.text().strip(),
        )

    def _review_derivation(self, decision: str) -> None:
        sources = self._snapshot.get("derivation_sources", [])
        if not any(item["state"] == "pending" for item in sources):
            return
        self.derivation_review_requested.emit(self.memory_id, decision)

    def _create_commitment(self) -> None:
        title = self.commitment_title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Title required", "Enter a commitment title.")
            return
        self.commitment_create_requested.emit(
            title,
            self.commitment_description_input.text().strip(),
            self.commitment_due_input.text().strip(),
            self.memory_id,
        )

    def _selected_commitment_id(self) -> str | None:
        row = self.commitment_table.currentRow()
        if row < 0:
            return None
        item = self.commitment_table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _update_commitment(self, state: str) -> None:
        commitment_id = self._selected_commitment_id()
        if commitment_id is not None:
            self.commitment_update_requested.emit(
                commitment_id, state, self.memory_id
            )

    def on_operation_completed(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def on_operation_failed(self, message: str) -> None:
        self.status_label.setText(f"Continuity operation failed: {message}")
