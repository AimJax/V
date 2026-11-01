"""Desktop controls for historical memory backfill and proposal review."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


MEMORY_TYPES = (
    "profile",
    "preference",
    "episodic",
    "relationship",
    "project",
    "fact",
)


class MemoryBackfillDialog(QDialog):
    """Run historical scans and explicitly review proposed memory records."""

    start_requested = Signal(bool)
    pause_requested = Signal()
    status_requested = Signal()
    candidates_requested = Signal(str)
    approve_requested = Signal(str, object)
    reject_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._candidates: list[dict] = []
        self._selected_candidate_id: str | None = None
        self._loading = False
        self._scan_running = False
        self._review_pending = False

        self.setWindowTitle("V — Historical Memory Backfill")
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
        self.resize(1080, 760)
        self.setMinimumSize(820, 560)

        self._build_ui()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(max(self.width(), min(820, available.width())), available.width())
        height = min(max(self.height(), min(560, available.height())), available.height())
        self.setMinimumSize(min(820, width), min(560, height))
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("Historical Memory Backfill")
        title.setStyleSheet("font-size: 18pt; font-weight: 650;")
        subtitle = QLabel(
            "Re-examine saved user messages. New discoveries remain proposals "
            "until you approve them."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        progress_row = QHBoxLayout()
        self.progress_status = QLabel("No historical scan started")
        self.progress_status.setObjectName("muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        progress_row.addWidget(self.progress_status, 1)
        progress_row.addWidget(self.progress_bar, 2)
        root.addLayout(progress_row)

        self.progress_details = QLabel(
            "0 messages scanned · 0 proposals · 0 candidates skipped"
        )
        self.progress_details.setObjectName("muted")
        root.addWidget(self.progress_details)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start / Resume scan")
        self.new_run_button = QPushButton("New full scan…")
        self.pause_button = QPushButton("Pause")
        self.refresh_button = QPushButton("Refresh proposals")
        self.review_filter = QComboBox()
        for label, value in (
            ("Pending review", "pending"),
            ("Approved", "approved"),
            ("Rejected", "rejected"),
            ("Duplicates", "duplicate"),
            ("All proposals", "all"),
        ):
            self.review_filter.addItem(label, value)
        self.start_button.clicked.connect(self._start_scan)
        self.new_run_button.clicked.connect(self._start_new_run)
        self.pause_button.clicked.connect(self._pause_scan)
        self.refresh_button.clicked.connect(self._request_candidates)
        self.review_filter.currentIndexChanged.connect(
            lambda _index: self._request_candidates()
        )
        controls.addWidget(self.start_button)
        controls.addWidget(self.new_run_button)
        controls.addWidget(self.pause_button)
        controls.addStretch(1)
        controls.addWidget(self.review_filter)
        controls.addWidget(self.refresh_button)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.candidate_table = QTableWidget(0, 4)
        self.candidate_table.setHorizontalHeaderLabels(
            ["Type", "Subject", "Confidence", "Source"]
        )
        self.candidate_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.candidate_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.candidate_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.candidate_table.setAlternatingRowColors(True)
        self.candidate_table.setWordWrap(False)
        self.candidate_table.verticalHeader().setVisible(False)
        header = self.candidate_table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            2,
            self.candidate_table.horizontalHeader().ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            self.candidate_table.horizontalHeader().ResizeMode.ResizeToContents,
        )
        self.candidate_table.currentCellChanged.connect(
            self._on_candidate_selected
        )
        splitter.addWidget(self.candidate_table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(8)

        self.candidate_heading = QLabel("Select a proposal")
        self.candidate_heading.setStyleSheet("font-size: 12pt; font-weight: 650;")
        detail_layout.addWidget(self.candidate_heading)

        self.candidate_id_label = QLabel("No proposal selected")
        self.candidate_id_label.setObjectName("muted")
        self.candidate_id_label.setWordWrap(True)
        detail_layout.addWidget(self.candidate_id_label)

        self.suggested_summary = QLabel("The model's suggested summary will appear here.")
        self.suggested_summary.setObjectName("muted")
        self.suggested_summary.setWordWrap(True)
        detail_layout.addWidget(self.suggested_summary)

        evidence_label = QLabel("Verbatim source evidence")
        evidence_label.setStyleSheet("font-weight: 650;")
        detail_layout.addWidget(evidence_label)
        self.evidence_text = QPlainTextEdit()
        self.evidence_text.setReadOnly(True)
        self.evidence_text.setMaximumHeight(105)
        detail_layout.addWidget(self.evidence_text)

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.memory_type = QComboBox()
        for value in MEMORY_TYPES:
            self.memory_type.addItem(value.replace("_", " ").title(), value)
        self.subject_input = QLineEdit()
        self.content_input = QTextEdit()
        self.content_input.setMinimumHeight(75)
        self.content_input.setMaximumHeight(120)
        self.memory_key_input = QLineEdit()
        self.confidence_input = QDoubleSpinBox()
        self.confidence_input.setRange(0.0, 1.0)
        self.confidence_input.setDecimals(2)
        self.confidence_input.setSingleStep(0.05)
        self.importance_input = QSpinBox()
        self.importance_input.setRange(1, 5)

        form.addRow("Memory type", self.memory_type)
        form.addRow("Subject", self.subject_input)
        form.addRow("Content to save", self.content_input)
        form.addRow("Memory key", self.memory_key_input)
        form.addRow("Confidence", self.confidence_input)
        form.addRow("Importance", self.importance_input)
        detail_layout.addLayout(form)

        self.review_note_input = QLineEdit()
        self.review_note_input.setPlaceholderText(
            "Optional reason for rejecting this proposal"
        )
        detail_layout.addWidget(self.review_note_input)

        actions = QHBoxLayout()
        self.reject_button = QPushButton("Reject proposal")
        self.approve_button = QPushButton("Approve memory")
        self.approve_button.setObjectName("primary")
        self.reject_button.clicked.connect(self._reject_selected)
        self.approve_button.clicked.connect(self._approve_selected)
        actions.addWidget(self.reject_button)
        actions.addStretch(1)
        actions.addWidget(self.approve_button)
        detail_layout.addLayout(actions)

        self.detail_status = QLabel("Approval creates an active memory; rejection is retained in review history.")
        self.detail_status.setObjectName("muted")
        self.detail_status.setWordWrap(True)
        detail_layout.addWidget(self.detail_status)

        splitter.addWidget(detail)
        splitter.setSizes([420, 640])
        root.addWidget(splitter, 1)

        self._set_candidate_editor_enabled(False)
        self._update_controls()

    def _start_scan(self) -> None:
        if self._scan_running:
            return
        self._scan_running = True
        self.detail_status.setText("Starting or resuming the historical scan…")
        self._update_controls()
        self.start_requested.emit(False)

    def _pause_scan(self) -> None:
        if not self._scan_running:
            return
        self.pause_requested.emit()

    def _start_new_run(self) -> None:
        answer = QMessageBox.question(
            self,
            "Start another full-history scan?",
            "This reprocesses the full conversation history with the current "
            "extraction rules. Previous runs, decisions, and accepted memories "
            "are retained. Existing memories will not be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._scan_running = True
            self.detail_status.setText("Starting a new full-history scan…")
            self._update_controls()
            self.start_requested.emit(True)

    def _request_candidates(self) -> None:
        self.candidates_requested.emit(str(self.review_filter.currentData() or "pending"))

    def _set_candidate_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self.memory_type,
            self.subject_input,
            self.content_input,
            self.memory_key_input,
            self.confidence_input,
            self.importance_input,
            self.review_note_input,
            self.approve_button,
            self.reject_button,
        ):
            widget.setEnabled(enabled and not self._review_pending)

    def _on_candidate_selected(
        self,
        row: int,
        _column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if row < 0 or row >= len(self._candidates):
            self._selected_candidate_id = None
            self._clear_candidate()
            return
        item = self.candidate_table.item(row, 0)
        candidate_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        candidate = next(
            (entry for entry in self._candidates if entry["id"] == candidate_id),
            None,
        )
        if candidate is None:
            self._selected_candidate_id = None
            self._clear_candidate()
            return

        self._selected_candidate_id = candidate["id"]
        payload = candidate["payload"]
        self._loading = True
        self.candidate_heading.setText(
            f"Proposal · {candidate['status'].title()}"
        )
        self.candidate_id_label.setText(
            f"Proposal ID: {candidate['id']} · "
            f"Conversation: {payload['source_conversation_id']} · "
            f"Message: {payload['source_message_id']}"
        )
        self.suggested_summary.setText(
            "Model suggestion: " + payload.get("model_content", "")
        )
        self.evidence_text.setPlainText(payload["evidence"])
        self.memory_type.setCurrentIndex(
            max(0, self.memory_type.findData(payload["memory_type"]))
        )
        self.subject_input.setText(payload["subject"])
        self.content_input.setPlainText(payload["content"])
        self.memory_key_input.setText(payload["memory_key"])
        self.confidence_input.setValue(float(payload["confidence"]))
        self.importance_input.setValue(int(payload["importance"]))
        self.review_note_input.clear()
        note = candidate.get("review_note")
        if note:
            self.detail_status.setText(note)
        else:
            self.detail_status.setText(
                "The content field defaults to the verbatim evidence. "
                "Edit it before approval if you want a cleaner memory statement."
            )
        self._loading = False
        pending = candidate["status"] == "pending"
        self._set_candidate_editor_enabled(pending)
        self._update_controls()

    def _clear_candidate(self) -> None:
        self._loading = True
        self.candidate_heading.setText("Select a proposal")
        self.candidate_id_label.setText("No proposal selected")
        self.suggested_summary.setText(
            "The model's suggested summary will appear here."
        )
        self.evidence_text.clear()
        self.memory_type.setCurrentIndex(0)
        self.subject_input.clear()
        self.content_input.clear()
        self.memory_key_input.clear()
        self.confidence_input.setValue(0.0)
        self.importance_input.setValue(3)
        self.review_note_input.clear()
        self._loading = False
        self._set_candidate_editor_enabled(False)

    def _approve_selected(self) -> None:
        if self._selected_candidate_id is None or self._review_pending:
            return
        content = self.content_input.toPlainText().strip()
        key = self.memory_key_input.text().strip()
        if not content or not key:
            QMessageBox.warning(
                self,
                "Memory content and key required",
                "A memory needs non-empty content and a unique memory key.",
            )
            return
        changes = {
            "memory_type": str(self.memory_type.currentData()),
            "subject": self.subject_input.text().strip(),
            "content": content,
            "memory_key": key,
            "confidence": self.confidence_input.value(),
            "importance": self.importance_input.value(),
        }
        self._review_pending = True
        self._update_controls()
        self.approve_requested.emit(self._selected_candidate_id, changes)

    def _reject_selected(self) -> None:
        if self._selected_candidate_id is None or self._review_pending:
            return
        answer = QMessageBox.question(
            self,
            "Reject proposal?",
            "This proposal will not become an active memory. Its review record "
            "will be retained and can be inspected later.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._review_pending = True
        self._update_controls()
        self.reject_requested.emit(
            self._selected_candidate_id,
            self.review_note_input.text().strip(),
        )

    def set_progress(self, run: dict | None) -> None:
        if run is None or run.get("status") == "not_started":
            self.progress_status.setText("No historical scan started")
            self.progress_bar.setValue(0)
            self.progress_details.setText(
                "0 messages scanned · 0 proposals · 0 candidates skipped"
            )
            self._scan_running = False
            self._update_controls()
            return

        status = str(run.get("status", "unknown"))
        total = int(run.get("total_messages", 0))
        processed = int(run.get("processed_messages", 0))
        found = int(run.get("candidates_found", 0))
        skipped = int(run.get("candidates_skipped", 0))
        percent = int(processed * 100 / total) if total else 100
        self.progress_status.setText(f"Historical scan: {status.title()}")
        self.progress_bar.setValue(min(100, max(0, percent)))
        self.progress_details.setText(
            f"{processed:,} / {total:,} messages · "
            f"{found:,} proposals · {skipped:,} skipped"
        )
        if run.get("last_error"):
            self.detail_status.setText(str(run["last_error"]))
        self._scan_running = status == "running"
        self._update_controls()

    def set_candidates(self, candidates: list[dict]) -> None:
        selected_id = self._selected_candidate_id
        self._candidates = list(candidates)
        self._review_pending = False
        self.candidate_table.setRowCount(len(self._candidates))
        selected_row = -1

        for row, candidate in enumerate(self._candidates):
            payload = candidate["payload"]
            values = (
                payload["memory_type"].replace("_", " ").title(),
                payload["subject"],
                f"{float(payload['confidence']):.2f}",
                str(payload["source_message_id"]),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, candidate["id"])
                self.candidate_table.setItem(row, column, item)
            self.candidate_table.setRowHeight(row, 34)
            if candidate["id"] == selected_id:
                selected_row = row

        if selected_row < 0 and self._candidates:
            selected_row = 0
        if selected_row >= 0:
            self.candidate_table.setCurrentCell(selected_row, 0)
            self.candidate_table.selectRow(selected_row)
        else:
            self.candidate_table.clearSelection()
            self.candidate_table.setCurrentCell(-1, -1)
            self._selected_candidate_id = None
            self._clear_candidate()

        self._update_controls()

    def on_review_changed(self) -> None:
        self._review_pending = False
        self._request_candidates()
        self.detail_status.setText("Review decision saved.")
        self._update_controls()

    def on_operation_failed(self, message: str) -> None:
        self._review_pending = False
        self.status_requested.emit()
        self.detail_status.setText(f"Operation failed: {message}")
        self._set_candidate_editor_enabled(
            self._selected_candidate_id is not None
        )
        self._update_controls()

    def on_backfill_completed(self, run: dict) -> None:
        self.set_progress(run)
        self._scan_running = False
        self.detail_status.setText(
            "Historical scan completed. Review the proposals before approving them."
        )
        self._request_candidates()
        self._update_controls()

    def on_backfill_paused(self) -> None:
        self._scan_running = False
        self.status_requested.emit()
        self.detail_status.setText(
            "Historical scan paused at the last committed batch. It can be resumed."
        )
        self._update_controls()

    def _update_controls(self) -> None:
        self.start_button.setEnabled(not self._scan_running)
        self.new_run_button.setEnabled(not self._scan_running)
        self.pause_button.setEnabled(self._scan_running)
        self.refresh_button.setEnabled(not self._review_pending)
        self.review_filter.setEnabled(not self._review_pending)
        pending = (
            self._selected_candidate_id is not None
            and self.candidate_table.currentRow() >= 0
            and self._candidates[self.candidate_table.currentRow()]["status"] == "pending"
        )
        self.approve_button.setEnabled(pending and not self._review_pending)
        self.reject_button.setEnabled(pending and not self._review_pending)

