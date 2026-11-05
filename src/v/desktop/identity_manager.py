"""Inspection and review UI for V's persistent identity."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class IdentityManagerDialog(QDialog):
    """Show foundational/developed traits and review proposed identity changes."""

    refresh_requested = Signal()
    review_requested = Signal(str, str)
    trait_update_requested = Signal(str, dict)
    proposal_requested = Signal(str, str)
    export_requested = Signal(str, bool)
    import_requested = Signal(str)

    CATEGORIES = [
        "temperament", "communication", "value", "boundary",
        "interest", "preference", "curiosity", "aesthetic", "habit",
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("V — Persistent Identity")
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        self.summary = QLabel("Loading V's identity…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.tabs = QTabWidget()
        self.traits_list = QListWidget()
        self.proposals_list = QListWidget()
        self.history_list = QListWidget()
        self.tabs.addTab(self.traits_list, "Identity traits")
        self.tabs.addTab(self.proposals_list, "Proposed changes")
        self.tabs.addTab(self.history_list, "Revision history")
        layout.addWidget(self.tabs, 1)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        layout.addWidget(self.details)

        actions = QHBoxLayout()
        self.propose_button = QPushButton("Propose trait")
        self.edit_button = QPushButton("Edit selected trait")
        self.accept_button = QPushButton("Accept")
        self.reject_button = QPushButton("Reject")
        self.defer_button = QPushButton("Defer")
        self.refresh_button = QPushButton("Refresh")
        self.export_button = QPushButton("Export backup")
        self.import_button = QPushButton("Restore backup")
        self.close_button = QPushButton("Close")

        for button in (
            self.propose_button, self.edit_button, self.accept_button,
            self.reject_button, self.defer_button, self.refresh_button,
            self.export_button, self.import_button, self.close_button,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)

        self.traits_list.currentItemChanged.connect(self._show_trait)
        self.proposals_list.currentItemChanged.connect(self._show_proposal)
        self.history_list.currentItemChanged.connect(self._show_revision)
        self.propose_button.clicked.connect(self._propose_trait)
        self.edit_button.clicked.connect(self._edit_trait)
        self.accept_button.clicked.connect(lambda: self._review("accept"))
        self.reject_button.clicked.connect(lambda: self._review("reject"))
        self.defer_button.clicked.connect(lambda: self._review("defer"))
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.export_button.clicked.connect(self._export_backup)
        self.import_button.clicked.connect(self._import_backup)
        self.close_button.clicked.connect(self.close)
        self._set_selection_state()

    def set_data(self, snapshot, proposals, revisions) -> None:
        self.summary.setText(
            f"{snapshot.display_name}  ·  revision {snapshot.revision}\n"
            f"{snapshot.summary}\n"
            "Foundational traits are seeded from checked-in product guidance. "
            "Developed traits require review and retain evidence references. "
            "Local behavior reviews may suggest candidates; nothing is applied automatically."
        )
        self.traits_list.clear()
        for trait in snapshot.traits:
            kind = "FOUNDATION" if trait.foundational else "DEVELOPED"
            item = QListWidgetItem(
                f"{kind}  ·  {trait.category}  ·  {trait.status}\n{trait.description}"
            )
            item.setData(Qt.ItemDataRole.UserRole, ("trait", trait))
            self.traits_list.addItem(item)

        self.proposals_list.clear()
        for proposal in proposals:
            item = QListWidgetItem(
                f"{proposal.category}  ·  {proposal.origin}  ·  "
                f"confidence {proposal.confidence:.2f}\n{proposal.description}"
            )
            item.setData(Qt.ItemDataRole.UserRole, ("proposal", proposal))
            self.proposals_list.addItem(item)

        self.history_list.clear()
        for revision in revisions:
            item = QListWidgetItem(
                f"Revision {revision['revision']}  ·  {revision['action']}\n"
                f"{revision['created_at']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, ("revision", revision))
            self.history_list.addItem(item)

        if self.traits_list.count():
            self.traits_list.setCurrentRow(0)
        elif self.proposals_list.count():
            self.tabs.setCurrentWidget(self.proposals_list)
            self.proposals_list.setCurrentRow(0)
        else:
            self.details.setPlainText("No identity traits or pending proposals.")
        self._set_selection_state()

    def _selected(self):
        current_tab = self.tabs.currentWidget()
        if current_tab is self.history_list:
            return None
        listing = self.proposals_list if current_tab is self.proposals_list else self.traits_list
        item = listing.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_trait(self, current, _previous=None) -> None:
        if current is None:
            self._set_selection_state()
            return
        kind, trait = current.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText(
            f"Category: {trait.category}\n"
            f"Origin: {trait.origin}\nStatus: {trait.status}\n"
            f"Confidence: {trait.confidence:.2f}\n"
            f"Foundational: {'yes' if trait.foundational else 'no'}\n"
            f"Rationale: {trait.rationale}\n"
            f"Evidence: {', '.join(trait.evidence_refs) or 'None recorded'}\n"
            f"Created: {trait.created_at}\nUpdated: {trait.updated_at}"
        )
        self._set_selection_state()

    def _show_proposal(self, current, _previous=None) -> None:
        if current is None:
            self._set_selection_state()
            return
        _kind, proposal = current.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText(
            f"Category: {proposal.category}\n"
            f"Origin: {proposal.origin}\nStatus: {proposal.status}\n"
            f"Confidence: {proposal.confidence:.2f}\n"
            f"Rationale: {proposal.rationale}\n"
            f"Evidence: {', '.join(proposal.evidence_refs) or 'User-stated'}\n"
            f"Created: {proposal.created_at}"
        )
        self._set_selection_state()

    def _show_revision(self, current, _previous=None) -> None:
        if current is None:
            self._set_selection_state()
            return
        _kind, revision = current.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText(
            f"Revision: {revision['revision']}\n"
            f"Action: {revision['action']}\n"
            f"Trait ID: {revision['trait_id'] or '—'}\n"
            f"Proposal ID: {revision['proposal_id'] or '—'}\n"
            f"Details: {revision['details']}\n"
            f"Timestamp: {revision['created_at']}"
        )
        self._set_selection_state()

    def _set_selection_state(self) -> None:
        selected = self._selected()
        is_proposal = bool(selected and selected[0] == "proposal")
        is_editable_trait = bool(selected and selected[0] == "trait")
        self.accept_button.setEnabled(is_proposal)
        self.reject_button.setEnabled(is_proposal)
        self.defer_button.setEnabled(is_proposal)
        self.edit_button.setEnabled(is_editable_trait)

    def _export_backup(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export V identity backup",
            "v-identity-backup.json",
            "JSON files (*.json)",
        )
        if path:
            answer = QMessageBox.warning(
                self,
                "Export plaintext identity backup?",
                "This JSON backup is unencrypted and contains V's identity, proposals, and revision history. Anyone with access to the file can read it. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = Path(path).exists()
            if overwrite:
                answer = QMessageBox.warning(
                    self,
                    "Replace existing backup?",
                    "The selected backup file already exists. Replace it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self.export_requested.emit(path, overwrite)

    def _import_backup(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Restore V identity backup",
            "",
            "JSON files (*.json)",
        )
        if path:
            answer = QMessageBox.warning(
                self,
                "Replace current identity?",
                "This backup is plaintext. Restoring it replaces V's current identity, proposals, and revision history. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.import_requested.emit(path)

    def on_backup_completed(self, message: str) -> None:
        QMessageBox.information(self, "Identity backup", message)
        self.refresh_requested.emit()

    def _review(self, decision: str) -> None:
        selected = self._selected()
        if not selected or selected[0] != "proposal":
            return
        self.review_requested.emit(selected[1].id, decision)

    def _propose_trait(self) -> None:
        category, accepted = QInputDialog.getItem(
            self, "Propose an identity trait", "Category:",
            self.CATEGORIES, 0, False,
        )
        if not accepted:
            return
        description, accepted = QInputDialog.getText(
            self, "Propose an identity trait", "Describe the trait:"
        )
        if accepted and description.strip():
            self.proposal_requested.emit(category, description.strip())

    def _edit_trait(self) -> None:
        selected = self._selected()
        if not selected or selected[0] != "trait":
            return
        trait = selected[1]
        description, accepted = QInputDialog.getMultiLineText(
            self, "Edit selected identity trait", "Description:", trait.description
        )
        if accepted and description.strip() and description.strip() != trait.description:
            self.trait_update_requested.emit(
                trait.id,
                {"description": description.strip(), "reviewer_note": "Edited by user in Identity Manager."},
            )

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Identity operation failed", message)
