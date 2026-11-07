"""Read-only preview of the memory context assembled for a query."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class MemoryContextPreviewDialog(QDialog):
    preview_requested = Signal(str)
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("V — Memory Context Preview")
        self.resize(780, 680)
        self.setMinimumSize(620, 480)

        root = QVBoxLayout(self)
        heading = QLabel("Preview memory retrieval")
        heading.setStyleSheet("font-size: 17pt; font-weight: 650;")
        explanation = QLabel(
            "Enter a representative message. This runs the configured local retrieval "
            "path and shows the exact memory context assembled for the model. "
            "Semantic preview may call the configured local embedding service."
        )
        explanation.setWordWrap(True)
        root.addWidget(heading)
        root.addWidget(explanation)

        query_row = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Example: What are the current project priorities?")
        self.preview_button = QPushButton("Preview")
        self.cancel_button = QPushButton("Cancel")
        self.preview_button.clicked.connect(self._preview)
        self.cancel_button.clicked.connect(
            lambda: self.cancel_requested.emit()
        )
        query_row.addWidget(self.query_input, 1)
        query_row.addWidget(self.preview_button)
        query_row.addWidget(self.cancel_button)
        root.addLayout(query_row)

        self.status_label = QLabel("No preview generated.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Selected memories and assembled model context appear here.")
        root.addWidget(self.output, 1)

    def closeEvent(self, event) -> None:
        self.cancel_requested.emit()
        super().closeEvent(event)

    def _preview(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Query required", "Enter a representative message.")
            return
        self.preview_button.setEnabled(False)
        self.status_label.setText("Retrieving relevant memories…")
        self.preview_requested.emit(query)

    def set_preview(self, result: dict) -> None:
        self.preview_button.setEnabled(True)
        memories = result.get("memories", [])
        mode = "hybrid semantic + keyword" if result.get("semantic") else "keyword"
        fallback = result.get("fallback_reason")
        status = f"{len(memories)} memory record(s) selected · {mode} retrieval"
        if fallback:
            status += f" · fallback: {fallback}"
        self.status_label.setText(status)

        lines = [
            f"QUERY\n{result.get('query', '')}",
            f"RETRIEVAL QUERY\n{result.get('retrieval_query', result.get('query', ''))}",
            "",
            "SELECTED MEMORY RECORDS",
        ]
        if not memories:
            lines.append("(none)")
        for memory in memories:
            lines.extend([
                "",
                (
                    f"[{memory['memory_type']}; {memory['provenance']}; "
                    f"confidence={memory['confidence']:.2f}; "
                    f"temporal_state={memory.get('temporal_state', 'unspecified')}; "
                    f"id={memory['memory_id']}]"
                ),
                f"Subject: {memory['subject']}",
                f"Valid: {memory.get('valid_from') or 'unbounded'} → "
                f"{memory.get('valid_until') or 'unbounded'}",
                f"Source date: {memory.get('source_created_at') or 'not recorded'}",
                memory["content"],
            ])
        lines.extend([
            "",
            "SELECTED PROSPECTIVE COMMITMENTS",
        ])
        commitments = result.get("commitments", [])
        if not commitments:
            lines.append("(none)")
        for item in commitments:
            lines.append(
                f"- {item['title']} [state={item['state']}; "
                f"due={item.get('due_at') or 'not specified'}; "
                f"source={item.get('source_memory_id') or 'not linked'}]"
            )
            if item.get("description"):
                lines.append(f"  {item['description']}")
            if item.get("source_evidence"):
                lines.append(f"  Source evidence: {item['source_evidence']}")
        lines.extend([
            "",
            "EXACT MEMORY-CONTEXT BLOCK",
            result.get("context") or "(no memory context will be injected)",
        ])
        self.output.setPlainText("\n".join(lines))

    def on_preview_failed(self, message: str) -> None:
        self.preview_button.setEnabled(True)
        self.status_label.setText(f"Preview failed: {message}")

    def on_preview_cancelled(self) -> None:
        self.preview_button.setEnabled(True)
        self.status_label.setText("Memory preview cancelled.")
