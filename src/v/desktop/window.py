"""Dark Qt Widgets interface for V's local desktop companion."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from v.desktop.service import DesktopSnapshot, DesktopTurnResult
from v.desktop.settings_dialog import SettingsDialog
from v.desktop.memory_manager import MemoryManagerDialog
from v.desktop.memory_continuity_dialog import MemoryContinuityDialog
from v.desktop.memory_context_preview import MemoryContextPreviewDialog
from v.desktop.memory_backfill_dialog import MemoryBackfillDialog
from v.desktop.identity_manager import IdentityManagerDialog
from v.desktop.cognitive_manager import CognitiveManagerDialog
from v.cognition import CognitiveStore
from v.chat import _configured_data_path
from v.core.config import load_settings
from v.desktop.thread import DesktopRuntimeThread
from v.providers.base import ChatMessage
from v.voice.recorder import PushToTalkRecorder


STYLESHEET = """
QMainWindow, QWidget#root {
    background: #111318;
    color: #e7e9ef;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QFrame#sidebar {
    background: #171a21;
    border: 1px solid #252a34;
    border-radius: 12px;
}
QLabel#brand {
    color: #f4f5f8;
    font-size: 22pt;
    font-weight: 650;
}
QLabel#muted {
    color: #8d95a5;
}
QLabel#status {
    color: #8ed8ad;
    background: #1b3028;
    border: 1px solid #294b3a;
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 9pt;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
    color: #d5d9e2;
}
QListWidget::item {
    padding: 10px 9px;
    border-radius: 7px;
    margin: 2px 0;
}
QListWidget::item:selected {
    background: #2b3342;
    color: #ffffff;
}
QListWidget::item:hover:!selected {
    background: #222833;
}
QPushButton {
    background: #252b36;
    border: 1px solid #343c4a;
    border-radius: 8px;
    padding: 9px 13px;
    color: #edf0f6;
}
QPushButton:hover {
    background: #30394a;
}
QPushButton:disabled {
    color: #656d7b;
    background: #1c2028;
    border-color: #292f39;
}
QPushButton#primary {
    background: #d7e3ff;
    color: #171d29;
    border: none;
    font-weight: 650;
    padding-left: 20px;
    padding-right: 20px;
}
QPushButton#primary:hover {
    background: #c1d3fa;
}
QPlainTextEdit {
    background: #191d25;
    color: #f0f2f7;
    border: 1px solid #333b49;
    border-radius: 9px;
    padding: 10px;
    selection-background-color: #536a91;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: #3a4250;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QStatusBar {
    background: #171a21;
    color: #8992a1;
}
"""


class MessageBubble(QFrame):
    """A selectable, plain-text chat message bubble."""

    def __init__(self, role: str, content: str = "") -> None:
        super().__init__()
        self.setObjectName("messageBubble")
        self.setMaximumWidth(820)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        self.setStyleSheet(
            "QFrame#messageBubble {"
            "background: #202631;"
            "border: 1px solid #303947;"
            "border-radius: 11px;"
            "}"
            if role == "V"
            else
            "QFrame#messageBubble {"
            "background: #293246;"
            "border: 1px solid #3b4a66;"
            "border-radius: 11px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)

        self.role_label = QLabel(role)
        self.role_label.setObjectName("muted")
        self.role_label.setStyleSheet(
            "color: #9aa9c5; font-weight: 650; border: none; background: transparent;"
        )

        self.content_label = QLabel(content)
        self.content_label.setTextFormat(Qt.TextFormat.PlainText)
        self.content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.content_label.setWordWrap(True)
        self.content_label.setStyleSheet(
            "color: #edf0f6; border: none; background: transparent;"
        )

        layout.addWidget(self.role_label)
        layout.addWidget(self.content_label)

    def set_content(self, content: str) -> None:
        self.content_label.setText(content)


class DesktopWindow(QMainWindow):
    """Main desktop shell; runtime and model operations live in a QThread."""

    def __init__(
        self,
        runtime: DesktopRuntimeThread | None = None,
        *,
        auto_start: bool = True,
    ) -> None:
        super().__init__()
        self.runtime = runtime or DesktopRuntimeThread()
        self._ready = False
        self._busy = False
        self._assistant_bubble: MessageBubble | None = None
        self._assistant_text = ""
        self._last_snapshot: DesktopSnapshot | None = None
        self.memory_manager_dialog: MemoryManagerDialog | None = None
        self.memory_continuity_dialog: MemoryContinuityDialog | None = None
        self.memory_context_preview_dialog: MemoryContextPreviewDialog | None = None
        self.memory_backfill_dialog: MemoryBackfillDialog | None = None
        self.identity_manager_dialog: IdentityManagerDialog | None = None
        self.cognitive_manager_dialog: CognitiveManagerDialog | None = None
        self.cognitive_store: CognitiveStore | None = None
        self.settings_dialog: SettingsDialog | None = None
        self._voice_recorder: PushToTalkRecorder | None = None
        self._speech_player = None
        self._voice_user_bubble: MessageBubble | None = None
        self._voice_pending = False
        self._voice_enabled = False
        self._speak_replies = False

        self.setWindowTitle("V — Local AI Companion")
        self.resize(1280, 820)
        self.setMinimumSize(900, 620)
        self.setStyleSheet(STYLESHEET)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 10)
        root_layout.setSpacing(14)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter)

        self.sidebar = self._build_sidebar()
        splitter.addWidget(self.sidebar)

        self.chat_panel = self._build_chat_panel()
        splitter.addWidget(self.chat_panel)
        splitter.setSizes([260, 980])

        self.statusBar().showMessage("Starting local runtime…")

        self.runtime.ready.connect(self._on_ready)
        self.runtime.startup_failed.connect(self._on_startup_failed)
        self.runtime.token_received.connect(self._on_token)
        self.runtime.speech_audio_ready.connect(self._enqueue_speech_audio)
        self.runtime.speech_failed.connect(self._on_speech_failed)
        self.runtime.turn_completed.connect(self._on_turn_completed)
        self.runtime.voice_turn_completed.connect(self._on_voice_turn_completed)
        self.runtime.operation_failed.connect(self._on_operation_failed)
        self.runtime.session_changed.connect(self._on_session_changed)
        self.runtime.identity_ready.connect(self._on_identity_ready)
        self.runtime.identity_failed.connect(self._on_identity_failed)

        if auto_start:
            self.runtime.start()

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(310)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(15, 18, 15, 15)
        layout.setSpacing(12)

        brand = QLabel("V")
        brand.setObjectName("brand")
        subtitle = QLabel("LOCAL AI COMPANION")
        subtitle.setObjectName("muted")
        subtitle.setStyleSheet("font-size: 8pt; letter-spacing: 1px;")

        self.new_chat_button = QPushButton("+  New chat")
        self.new_chat_button.clicked.connect(self._new_conversation)
        self.new_chat_button.setEnabled(False)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self._open_settings)
        self.settings_button.setEnabled(False)

        self.identity_button = QPushButton("Identity")
        self.identity_button.clicked.connect(self._open_identity_manager)
        self.identity_button.setEnabled(False)

        self.cognitive_button = QPushButton("Cognitive state")
        self.cognitive_button.clicked.connect(self._open_cognitive_manager)
        self.cognitive_button.setEnabled(False)

        self.memory_manager_button = QPushButton("Memory manager")
        self.memory_manager_button.clicked.connect(self._open_memory_manager)
        self.memory_manager_button.setEnabled(False)
        self.cognitive_button.setEnabled(False)

        recent_label = QLabel("RECENT CONVERSATIONS")
        recent_label.setObjectName("muted")
        recent_label.setStyleSheet("font-size: 8pt; font-weight: 650;")

        self.conversation_list = QListWidget()
        self.conversation_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.conversation_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.conversation_list.currentItemChanged.connect(
            self._on_conversation_selected
        )
        self.conversation_list.setEnabled(False)

        self.sidebar_hint = QLabel("Your conversations stay on this PC.")
        self.sidebar_hint.setObjectName("muted")
        self.sidebar_hint.setWordWrap(True)
        self.sidebar_hint.setStyleSheet("font-size: 8pt;")

        layout.addWidget(brand)
        layout.addWidget(subtitle)
        layout.addSpacing(10)
        layout.addWidget(self.new_chat_button)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.identity_button)
        layout.addWidget(self.memory_manager_button)
        layout.addWidget(self.cognitive_button)
        layout.addSpacing(14)
        layout.addWidget(recent_label)
        layout.addWidget(self.conversation_list, 1)
        layout.addWidget(self.sidebar_hint)
        return sidebar

    def _build_chat_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 3, 3, 3)
        layout.setSpacing(13)

        header = QHBoxLayout()
        heading_column = QVBoxLayout()
        self.conversation_title = QLabel("Connecting to V…")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.conversation_title.setFont(title_font)

        self.model_label = QLabel("Waiting for LM Studio")
        self.model_label.setObjectName("muted")
        heading_column.addWidget(self.conversation_title)
        heading_column.addWidget(self.model_label)

        self.connection_label = QLabel("CONNECTING")
        self.connection_label.setObjectName("status")
        header.addLayout(heading_column)
        header.addStretch(1)
        header.addWidget(self.connection_label)
        layout.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(12, 12, 16, 12)
        self.messages_layout.setSpacing(13)
        self.messages_layout.addStretch(1)
        self.scroll_area.setWidget(self.messages_widget)
        layout.addWidget(self.scroll_area, 1)

        composer_row = QHBoxLayout()
        self.message_input = QPlainTextEdit()
        self.message_input.setPlaceholderText(
            "Message V…  (Enter for a new line)"
        )
        self.message_input.setFixedHeight(92)
        self.message_input.setEnabled(False)
        self.message_input.setTabChangesFocus(True)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primary")
        self.send_button.setFixedHeight(48)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._send_message)

        self.voice_button = QPushButton("Hold to talk")
        self.voice_button.setFixedHeight(48)
        self.voice_button.setEnabled(False)
        self.voice_button.setToolTip(
            "Press and hold to record locally. Release to transcribe and send."
        )
        self.voice_button.pressed.connect(self._start_voice_recording)
        self.voice_button.released.connect(self._stop_voice_recording)

        composer_row.addWidget(self.message_input, 1)
        composer_row.addWidget(self.voice_button)
        composer_row.addWidget(self.send_button)
        layout.addLayout(composer_row)

        privacy_note = QLabel(
            "Local inference  •  Private data stays on this PC  •  No cloud AI fallback"
        )
        privacy_note.setObjectName("muted")
        privacy_note.setStyleSheet("font-size: 8pt;")
        layout.addWidget(privacy_note)

        return panel

    def _append_bubble(self, role: str, content: str = "") -> MessageBubble:
        bubble = MessageBubble(role, content)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        if role == "You":
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
        else:
            row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignLeft)
            row.addStretch(1)

        index = max(0, self.messages_layout.count() - 1)
        self.messages_layout.insertLayout(index, row)
        QTimer.singleShot(
            0,
            lambda: self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            ),
        )
        return bubble

    def _clear_messages(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.layout() is not None:
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget() is not None:
                        widget = child.widget()
                        widget.setParent(None)
                        widget.deleteLater()
                item.layout().deleteLater()
            elif item.widget() is not None:
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()

        self._assistant_bubble = None
        self._assistant_text = ""

    def _apply_snapshot(self, snapshot: DesktopSnapshot) -> None:
        self._last_snapshot = snapshot
        self._ready = True

        self.conversation_title.setText(snapshot.conversation.title)
        self.model_label.setText(
            f"{snapshot.model}  •  "
            + (
                "semantic memory enabled"
                if snapshot.semantic_memory_enabled
                else "keyword memory"
            )
        )
        self.connection_label.setText(
            f"LOCAL  ·  {snapshot.network_mode}"
        )

        blocker = QSignalBlocker(self.conversation_list)
        self.conversation_list.clear()
        selected_item = None

        for conversation in snapshot.conversations:
            item = QListWidgetItem(conversation.title)
            item.setToolTip(conversation.title)
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            self.conversation_list.addItem(item)
            if conversation.id == snapshot.conversation.id:
                selected_item = item

        if selected_item is not None:
            self.conversation_list.setCurrentItem(selected_item)
        del blocker

        self._clear_messages()
        for message in snapshot.messages:
            role = "You" if message.role == "user" else "V"
            self._append_bubble(role, message.content)

        self.new_chat_button.setEnabled(True)
        self.memory_manager_button.setEnabled(True)
        self.cognitive_button.setEnabled(True)
        self.identity_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.conversation_list.setEnabled(True)
        self._configure_voice(snapshot)
        self.message_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.statusBar().showMessage(
            "Connected to the configured local inference server."
        )

    def _on_ready(self, snapshot: DesktopSnapshot) -> None:
        self._apply_snapshot(snapshot)

    def _on_startup_failed(self, message: str) -> None:
        self._ready = False
        self.memory_manager_button.setEnabled(False)
        self.identity_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.voice_button.setEnabled(False)
        self.connection_label.setText("NOT CONNECTED")
        self.connection_label.setStyleSheet(
            "color: #ffc0b4; background: #382521; "
            "border: 1px solid #624039; border-radius: 10px; padding: 5px 10px;"
        )
        self.conversation_title.setText("V could not start")
        self.model_label.setText("Check LM Studio and local configuration.")
        self._append_bubble("V", f"Local runtime error: {message}")
        self.statusBar().showMessage("Local runtime connection failed.")

    def _on_conversation_selected(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if current is None or not self._ready or self._busy:
            return
        conversation_id = current.data(Qt.ItemDataRole.UserRole)
        if conversation_id:
            self._stop_speech()
            self.runtime.select_conversation(str(conversation_id))

    def _open_settings(self) -> None:
        if not self._ready or self._busy:
            return

        if self.settings_dialog is None:
            dialog = SettingsDialog(self)
            dialog.save_requested.connect(self.runtime.save_settings)
            self.runtime.settings_ready.connect(dialog.set_snapshot)
            self.runtime.settings_saved.connect(dialog.on_saved)
            self.runtime.settings_operation_failed.connect(
                dialog.on_save_failed
            )
            self.settings_dialog = dialog
        elif self.settings_dialog._dirty or self.settings_dialog._saving:
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return

        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()
        self.runtime.get_settings()

    def _open_cognitive_manager(self) -> None:
        if not self._ready or self._busy:
            return

        if self.cognitive_manager_dialog is None:
            if self.cognitive_store is None:
                settings = load_settings()
                self.cognitive_store = CognitiveStore(
                    _configured_data_path(settings, "cognition_db")
                )
            self.cognitive_manager_dialog = CognitiveManagerDialog(
                self.cognitive_store, self
            )

        self.cognitive_manager_dialog.refresh()
        self.cognitive_manager_dialog.show()
        self.cognitive_manager_dialog.raise_()
        self.cognitive_manager_dialog.activateWindow()

    def _open_identity_manager(self) -> None:
        if not self._ready or self._busy:
            return

        if self.identity_manager_dialog is None:
            dialog = IdentityManagerDialog(self)
            dialog.refresh_requested.connect(self.runtime.get_identity)
            dialog.review_requested.connect(self.runtime.review_identity_proposal)
            dialog.trait_update_requested.connect(self.runtime.update_identity_trait)
            dialog.proposal_requested.connect(self.runtime.propose_identity_trait)
            dialog.export_requested.connect(self.runtime.export_identity)
            dialog.import_requested.connect(self.runtime.import_identity)
            self.runtime.identity_backup_completed.connect(dialog.on_backup_completed)
            self.runtime.identity_ready.connect(dialog.set_data)
            self.runtime.identity_failed.connect(dialog.show_error)
            self.identity_manager_dialog = dialog

        self.identity_manager_dialog.show()
        self.identity_manager_dialog.raise_()
        self.identity_manager_dialog.activateWindow()
        self.runtime.get_identity()

    def _on_identity_ready(self, _snapshot, _proposals, _revisions) -> None:
        self.statusBar().showMessage("V's persistent identity is up to date.")

    def _on_identity_failed(self, message: str) -> None:
        self.statusBar().showMessage(f"Identity operation failed: {message}")

    def _open_memory_manager(self) -> None:
        if not self._ready or self._busy:
            return

        if self.memory_manager_dialog is None:
            dialog = MemoryManagerDialog(self)
            dialog.backfill_requested.connect(self._open_memory_backfill)
            dialog.refresh_requested.connect(self.runtime.list_memories)
            dialog.update_requested.connect(self.runtime.update_memory)
            dialog.delete_requested.connect(self.runtime.delete_memory)
            dialog.confirm_requested.connect(self.runtime.confirm_memory)
            dialog.continuity_requested.connect(self._open_memory_continuity)
            dialog.context_preview_requested.connect(
                self._open_memory_context_preview
            )
            dialog.export_requested.connect(self.runtime.export_memories)
            dialog.import_requested.connect(self.runtime.import_memories)

            self.runtime.memory_list_ready.connect(dialog.set_memories)
            self.runtime.memory_updated.connect(dialog.on_memory_updated)
            self.runtime.memory_confirmed.connect(dialog.on_memory_confirmed)
            self.runtime.memory_deleted.connect(dialog.on_memory_deleted)
            self.runtime.memory_backup_completed.connect(
                dialog.on_backup_completed
            )
            self.runtime.memory_operation_failed.connect(
                dialog.on_operation_failed
            )
            self.memory_manager_dialog = dialog

        self.memory_manager_dialog.show()
        self.memory_manager_dialog.raise_()
        self.memory_manager_dialog.activateWindow()
        self.memory_manager_dialog.refresh()

    def _open_memory_context_preview(self) -> None:
        if not self._ready or self._busy:
            return

        if self.memory_context_preview_dialog is None:
            dialog = MemoryContextPreviewDialog(self)
            dialog.preview_requested.connect(self.runtime.preview_memory_context)
            dialog.cancel_requested.connect(
                self.runtime.cancel_memory_context_preview
            )
            self.runtime.memory_context_preview_ready.connect(dialog.set_preview)
            self.runtime.memory_context_preview_failed.connect(
                dialog.on_preview_failed
            )
            self.runtime.memory_context_preview_cancelled.connect(
                dialog.on_preview_cancelled
            )
            self.memory_context_preview_dialog = dialog

        self.memory_context_preview_dialog.show()
        self.memory_context_preview_dialog.raise_()
        self.memory_context_preview_dialog.activateWindow()

    def _open_memory_continuity(self, memory_id: str) -> None:
        if not self._ready or self._busy:
            return

        dialog = self.memory_continuity_dialog
        if dialog is not None and dialog.memory_id != memory_id:
            dialog.close()
            dialog.deleteLater()
            dialog = None
            self.memory_continuity_dialog = None

        if dialog is None:
            dialog = MemoryContinuityDialog(memory_id, self)
            dialog.refresh_requested.connect(self.runtime.get_memory_continuity)
            dialog.temporal_update_requested.connect(
                self.runtime.update_memory_temporal_state
            )
            dialog.derivation_review_requested.connect(
                self.runtime.review_memory_derivation
            )
            dialog.commitment_create_requested.connect(
                self.runtime.create_memory_commitment
            )
            dialog.commitment_update_requested.connect(
                self.runtime.update_memory_commitment
            )
            dialog.commitment_edit_requested.connect(
                self.runtime.edit_memory_commitment
            )
            dialog.consolidation_requested.connect(
                self.runtime.start_memory_consolidation
            )
            dialog.consolidation_cancel_requested.connect(
                self.runtime.cancel_memory_consolidation
            )
            self.runtime.memory_consolidation_completed.connect(
                dialog.on_consolidation_completed
            )
            self.runtime.memory_consolidation_failed.connect(
                dialog.on_operation_failed
            )
            self.runtime.memory_consolidation_cancelled.connect(
                dialog.on_consolidation_cancelled
            )
            self.runtime.memory_continuity_ready.connect(dialog.set_snapshot)
            self.runtime.memory_continuity_failed.connect(dialog.on_operation_failed)
            self.memory_continuity_dialog = dialog

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.refresh()

    def _open_memory_backfill(self) -> None:
        if not self._ready:
            return

        if self.memory_backfill_dialog is None:
            dialog = MemoryBackfillDialog(self)
            dialog.start_requested.connect(self.runtime.start_memory_backfill)
            dialog.pause_requested.connect(self.runtime.cancel_memory_backfill)
            dialog.status_requested.connect(
                self.runtime.get_memory_backfill_status
            )
            dialog.candidates_requested.connect(
                lambda status: self.runtime.list_memory_review_candidates(
                    status=status
                )
            )
            dialog.approve_requested.connect(
                self.runtime.approve_memory_candidate
            )
            dialog.reject_requested.connect(
                self.runtime.reject_memory_candidate
            )
            self.runtime.memory_backfill_progress.connect(dialog.set_progress)
            self.runtime.memory_backfill_completed.connect(
                dialog.on_backfill_completed
            )
            self.runtime.memory_backfill_paused.connect(dialog.on_backfill_paused)
            self.runtime.memory_backfill_failed.connect(
                dialog.on_operation_failed
            )
            self.runtime.memory_review_ready.connect(dialog.set_candidates)
            self.runtime.memory_review_changed.connect(dialog.on_review_changed)
            self.memory_backfill_dialog = dialog

        self.memory_backfill_dialog.show()
        self.memory_backfill_dialog.raise_()
        self.memory_backfill_dialog.activateWindow()
        self.runtime.get_memory_backfill_status()
        self.runtime.list_memory_review_candidates(
            status=str(self.memory_backfill_dialog.review_filter.currentData() or "pending")
        )

    def _new_conversation(self) -> None:
        if self._ready and not self._busy:
            self._stop_speech()
            self.runtime.new_conversation()

    def _on_session_changed(self, snapshot: DesktopSnapshot) -> None:
        self._apply_snapshot(snapshot)

    def _send_message(self) -> None:
        if not self._ready or self._busy:
            return

        self._stop_speech()
        self.runtime.interrupt_speech()
        text = self.message_input.toPlainText().strip()
        if not text:
            return

        self.message_input.clear()
        self._append_bubble("You", text)
        self._assistant_bubble = self._append_bubble("V")
        self._assistant_text = ""
        self._set_busy(True)
        self.statusBar().showMessage("Generating with the local model…")
        self.runtime.send_message(text)

    def _on_token(self, token: str) -> None:
        self._assistant_text += token
        if self._assistant_bubble is not None:
            self._assistant_bubble.set_content(self._assistant_text)

    def _enqueue_speech_audio(self, audio_wav: bytes) -> None:
        if not audio_wav:
            return
        try:
            from v.voice.playback import SpeechPlayback

            if self._speech_player is None:
                voice = (
                    self._last_snapshot.voice_settings
                    if self._last_snapshot is not None
                    else {}
                )
                output_id = str(voice.get("output_device_id", "") or "")
                self._speech_player = SpeechPlayback(
                    device_id=output_id,
                    parent=self,
                )
                self._speech_player.playback_failed.connect(
                    self._on_speech_failed
                )
            self._speech_player.enqueue(audio_wav)
            self.statusBar().showMessage("V is speaking…")
        except Exception as error:
            self._on_speech_failed(str(error))

    def _on_speech_failed(self, message: str) -> None:
        self.statusBar().showMessage(
            f"Text response is available; local speech failed: {message}"
        )

    def _stop_speech(self) -> None:
        if self._speech_player is not None:
            self._speech_player.stop()

    def _play_speech_response(
        self,
        audio_wav: bytes | None,
        speech_error: str | None,
        snapshot: DesktopSnapshot,
    ) -> None:
        # Retain compatibility with completed-turn audio results.
        if audio_wav:
            self._enqueue_speech_audio(audio_wav)
        elif speech_error:
            self._on_speech_failed(speech_error)

    def _on_turn_completed(self, result: DesktopTurnResult) -> None:
        if self._assistant_bubble is not None:
            self._assistant_bubble.set_content(result.response)
        self._apply_session_list(result.snapshot)
        self._set_busy(False)
        if result.audio_wav or result.speech_error:
            self._play_speech_response(
                result.audio_wav,
                result.speech_error,
                result.snapshot,
            )
        elif self._speech_player is not None and self._speech_player.is_playing:
            self.statusBar().showMessage("V is speaking…")
        else:
            self.statusBar().showMessage("Response completed.")

    def _configure_voice(self, snapshot: DesktopSnapshot) -> None:
        """Prepare a recorder object without touching audio hardware."""
        if self._voice_recorder is not None:
            if self._voice_recorder.is_recording:
                self._voice_recorder.cancel()
            self._voice_recorder.deleteLater()
            self._voice_recorder = None

        voice = snapshot.voice_settings
        self._voice_enabled = bool(snapshot.voice_enabled)
        self._speak_replies = bool(snapshot.speak_replies)

        self._voice_recorder = PushToTalkRecorder(
            device_id=str(voice.get("input_device_id", "") or ""),
            max_seconds=int(voice.get("max_utterance_seconds", 30)),
            minimum_speech_ms=int(
                voice.get("vad_min_speech_duration_ms", 250)
            ),
            parent=self,
        )
        self._voice_recorder.recording_started.connect(
            self._on_voice_recording_started
        )
        self._voice_recorder.recording_finished.connect(
            self._on_voice_recording_finished
        )
        self._voice_recorder.recording_failed.connect(
            self._on_voice_recording_failed
        )

        self.voice_button.setEnabled(self._voice_enabled and not self._busy)
        self.voice_button.setText(
            "Hold to talk" if self._voice_enabled else "Voice disabled"
        )
        if self._voice_enabled:
            self.statusBar().showMessage(
                "Local push-to-talk is enabled. The microphone is inactive until you press the voice button."
            )

    def _start_voice_recording(self) -> None:
        if not self._ready or self._busy:
            return
        self._stop_speech()
        self.runtime.interrupt_speech()
        if not self._voice_enabled or self._voice_recorder is None:
            self.statusBar().showMessage(
                "Enable voice interaction in Settings and restart V."
            )
            return

        try:
            self._voice_recorder.start()
        except Exception as error:
            self.voice_button.setText("Hold to talk")
            self.statusBar().showMessage(
                f"Could not start local microphone capture: {error}"
            )

    def _stop_voice_recording(self) -> None:
        if self._voice_recorder is not None and self._voice_recorder.is_recording:
            self._voice_recorder.stop()

    def _on_voice_recording_started(self) -> None:
        self.voice_button.setText("Listening… release to send")
        self.statusBar().showMessage(
            "MICROPHONE ACTIVE — audio is being held in memory locally."
        )

    def _on_voice_recording_finished(self, wav_data: bytes) -> None:
        self.voice_button.setText("Hold to talk")
        if not self._ready or self._busy:
            return

        self._voice_pending = True
        self._voice_user_bubble = self._append_bubble(
            "You",
            "Transcribing locally…",
        )
        self._assistant_bubble = self._append_bubble("V")
        self._assistant_text = ""
        self._set_busy(True)
        self.statusBar().showMessage(
            "Transcribing locally, then generating a response…"
        )
        self.runtime.send_voice_turn(wav_data)

    def _on_voice_recording_failed(self, message: str) -> None:
        self.voice_button.setText("Hold to talk")
        self.statusBar().showMessage(f"Voice input failed: {message}")

    def _on_voice_turn_completed(self, result) -> None:
        self._voice_pending = False
        if self._voice_user_bubble is not None:
            self._voice_user_bubble.set_content(result.transcription)
        self._voice_user_bubble = None

        if self._assistant_bubble is not None:
            self._assistant_bubble.set_content(result.turn.response)

        self._apply_session_list(result.turn.snapshot)
        self._set_busy(False)

        self._play_speech_response(
            result.audio_wav,
            result.speech_error,
            result.turn.snapshot,
        )
        if not result.audio_wav and not result.speech_error:
            if self._speech_player is not None and self._speech_player.is_playing:
                self.statusBar().showMessage("V is speaking…")
            else:
                self.statusBar().showMessage("Voice turn completed.")

    def _apply_session_list(self, snapshot: DesktopSnapshot) -> None:
        self._last_snapshot = snapshot
        self.conversation_title.setText(snapshot.conversation.title)
        blocker = QSignalBlocker(self.conversation_list)
        self.conversation_list.clear()
        selected_item = None
        for conversation in snapshot.conversations:
            item = QListWidgetItem(conversation.title)
            item.setToolTip(conversation.title)
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            self.conversation_list.addItem(item)
            if conversation.id == snapshot.conversation.id:
                selected_item = item
        if selected_item is not None:
            self.conversation_list.setCurrentItem(selected_item)
        del blocker

    def _remove_message_bubble(self, bubble: MessageBubble) -> None:
        """Remove an empty placeholder bubble from the conversation layout."""
        for index in range(self.messages_layout.count()):
            row = self.messages_layout.itemAt(index).layout()
            if row is None:
                continue
            if any(
                row.itemAt(child_index).widget() is bubble
                for child_index in range(row.count())
            ):
                self.messages_layout.takeAt(index)
                bubble.setParent(None)
                bubble.deleteLater()
                row.deleteLater()
                return

    def _on_operation_failed(self, message: str) -> None:
        if self._voice_pending:
            if self._voice_user_bubble is not None:
                self._voice_user_bubble.set_content(
                    f"Voice input failed: {message}"
                )
                self._voice_user_bubble = None
            self._voice_pending = False

            # Transcription can fail before chat generation begins. Remove the
            # empty assistant placeholder instead of labelling it a generation error.
            if self._assistant_bubble is not None and not self._assistant_text:
                self._remove_message_bubble(self._assistant_bubble)
                self._assistant_bubble = None

            self.statusBar().showMessage(f"Voice input failed: {message}")
            self._set_busy(False)
            return

        if self._assistant_bubble is not None and not self._assistant_text:
            self._assistant_bubble.set_content(
                f"Generation failed: {message}"
            )
        else:
            self.statusBar().showMessage(f"Operation failed: {message}")
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_button.setEnabled(self._ready and not busy)
        self.message_input.setEnabled(self._ready and not busy)
        self.new_chat_button.setEnabled(self._ready and not busy)
        self.memory_manager_button.setEnabled(self._ready and not busy)
        self.settings_button.setEnabled(self._ready and not busy)
        self.voice_button.setEnabled(
            self._ready and self._voice_enabled and not busy
        )
        self.conversation_list.setEnabled(self._ready and not busy)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._voice_recorder is not None and self._voice_recorder.is_recording:
            self._voice_recorder.cancel()
        if self._speech_player is not None:
            self._speech_player.close()

        if self.runtime.isRunning():
            self.runtime.request_shutdown()
            if not self.runtime.wait(5000):
                self.statusBar().showMessage(
                    "V is still closing its local runtime. Close again when finished."
                )
                event.ignore()
                return
        event.accept()
