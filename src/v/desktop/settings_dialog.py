"""Configurable local settings dialog for V's desktop application."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from v.desktop.service import DesktopSettingsSnapshot


class SettingsDialog(QDialog):
    """Edit model, generation, personality, memory, and privacy settings."""

    save_requested = Signal(object, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot: DesktopSettingsSnapshot | None = None
        self._loading = False
        self._dirty = False
        self._saving = False

        self.setWindowTitle("V — Settings")
        self.resize(760, 700)
        self.setMinimumSize(650, 580)
        self.setModal(False)

        self._build_ui()
        self._connect_dirty_signals()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 18pt; font-weight: 650;")
        subtitle = QLabel(
            "Changes are saved locally. Restart V before they take effect."
        )
        subtitle.setObjectName("muted")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_form = QFormLayout()
        general_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.provider_label = QLabel("LM Studio — local API")
        self.provider_label.setObjectName("muted")

        self.chat_model = QComboBox()
        self.chat_model.setMinimumWidth(300)

        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setDecimals(2)
        self.temperature.setSingleStep(0.05)

        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(1, 32768)
        self.max_tokens.setSingleStep(128)

        self.history_messages = QSpinBox()
        self.history_messages.setRange(2, 200)

        general_form.addRow("Provider", self.provider_label)
        general_form.addRow("Chat model", self.chat_model)
        general_form.addRow("Temperature", self.temperature)
        general_form.addRow("Maximum response tokens", self.max_tokens)
        general_form.addRow("Conversation history messages", self.history_messages)
        general_layout.addLayout(general_form)

        general_note = QLabel(
            "Only models currently exposed by your local LM Studio server are listed. "
            "V will never switch providers automatically."
        )
        general_note.setObjectName("muted")
        general_note.setWordWrap(True)
        general_layout.addWidget(general_note)
        general_layout.addStretch(1)
        self.tabs.addTab(general, "General")

        personality = QWidget()
        personality_layout = QVBoxLayout(personality)
        self.personality_path = QLabel("Personality file: —")
        self.personality_path.setObjectName("muted")
        self.personality_path.setWordWrap(True)

        self.personality_text = QTextEdit()
        self.personality_text.setPlaceholderText(
            "Define how V communicates, handles uncertainty, and maintains continuity…"
        )
        personality_layout.addWidget(self.personality_path)
        personality_layout.addWidget(self.personality_text, 1)
        self.tabs.addTab(personality, "Personality")

        memory = QWidget()
        memory_layout = QVBoxLayout(memory)
        memory_form = QFormLayout()
        memory_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.memory_enabled = QCheckBox("Enable long-term memory")
        self.automatic_extraction = QCheckBox(
            "Automatically extract explicit memories after idle time"
        )
        self.retrieval_enabled = QCheckBox(
            "Retrieve relevant memories during conversation"
        )
        self.embedding_model = QComboBox()
        self.minimum_confidence = QDoubleSpinBox()
        self.minimum_confidence.setRange(0.0, 1.0)
        self.minimum_confidence.setDecimals(2)
        self.minimum_confidence.setSingleStep(0.05)

        self.idle_delay = QDoubleSpinBox()
        self.idle_delay.setRange(0.0, 3600.0)
        self.idle_delay.setDecimals(1)
        self.idle_delay.setSuffix(" s")

        self.jobs_per_cycle = QSpinBox()
        self.jobs_per_cycle.setRange(1, 50)

        self.semantic_threshold = QDoubleSpinBox()
        self.semantic_threshold.setRange(0.0, 1.0)
        self.semantic_threshold.setDecimals(2)
        self.semantic_threshold.setSingleStep(0.05)

        self.retrieval_limit = QSpinBox()
        self.retrieval_limit.setRange(1, 50)

        self.retrieval_characters = QSpinBox()
        self.retrieval_characters.setRange(100, 20000)
        self.retrieval_characters.setSingleStep(200)

        memory_form.addRow(self.memory_enabled)
        memory_form.addRow(self.automatic_extraction)
        memory_form.addRow(self.retrieval_enabled)
        memory_form.addRow("Embedding model", self.embedding_model)
        memory_form.addRow("Minimum extraction confidence", self.minimum_confidence)
        memory_form.addRow("Idle delay before extraction", self.idle_delay)
        memory_form.addRow("Maximum extraction jobs per cycle", self.jobs_per_cycle)
        memory_form.addRow("Semantic similarity threshold", self.semantic_threshold)
        memory_form.addRow("Maximum retrieved memories", self.retrieval_limit)
        memory_form.addRow("Maximum memory context characters", self.retrieval_characters)
        memory_layout.addLayout(memory_form)

        memory_note = QLabel(
            "Memory extraction stores only explicit, validated statements. "
            "Disabling retrieval does not delete saved memories. "
            "The embedding model must be loaded in LM Studio when semantic retrieval is enabled."
        )
        memory_note.setObjectName("muted")
        memory_note.setWordWrap(True)
        memory_layout.addWidget(memory_note)
        memory_layout.addStretch(1)
        self.tabs.addTab(memory, "Memory")

        privacy = QWidget()
        privacy_layout = QVBoxLayout(privacy)
        self.offline_mode = QCheckBox(
            "Enable strict offline mode (block configured external web features)"
        )
        self.privacy_status = QLabel(
            "Local inference always uses the loopback LM Studio endpoint. "
            "Cloud AI fallback and telemetry are disabled. Web search and retrieval "
            "are not yet connected to the desktop app; enabling external access "
            "here does not activate them."
        )
        self.privacy_status.setObjectName("muted")
        self.privacy_status.setWordWrap(True)
        self.privacy_status.setMinimumHeight(85)

        privacy_layout.addWidget(self.offline_mode)
        privacy_layout.addWidget(self.privacy_status)
        privacy_layout.addSpacing(12)
        privacy_layout.addStretch(1)
        self.tabs.addTab(privacy, "Privacy")

        footer = QHBoxLayout()
        self.status_label = QLabel("Loading settings…")
        self.status_label.setObjectName("muted")

        self.save_button = QPushButton("Save changes")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.close_button)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self.memory_enabled.toggled.connect(self._update_memory_controls)
        self.retrieval_enabled.toggled.connect(self._update_memory_controls)

    def _connect_dirty_signals(self) -> None:
        widgets = (
            self.chat_model,
            self.temperature,
            self.max_tokens,
            self.history_messages,
            self.personality_text,
            self.memory_enabled,
            self.automatic_extraction,
            self.retrieval_enabled,
            self.embedding_model,
            self.minimum_confidence,
            self.idle_delay,
            self.jobs_per_cycle,
            self.semantic_threshold,
            self.retrieval_limit,
            self.retrieval_characters,
            self.offline_mode,
        )
        for widget in widgets:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._mark_dirty)
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(self._mark_dirty)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._mark_dirty)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._mark_dirty)
            elif isinstance(widget, QTextEdit):
                widget.textChanged.connect(self._mark_dirty)

    def set_snapshot(self, snapshot: DesktopSettingsSnapshot) -> None:
        self._snapshot = snapshot
        self._loading = True

        self.chat_model.clear()
        for model in snapshot.available_models:
            self.chat_model.addItem(model, model)
        model_index = self.chat_model.findData(snapshot.model)
        if model_index < 0:
            self.chat_model.addItem(snapshot.model, snapshot.model)
            model_index = self.chat_model.count() - 1
        self.chat_model.setCurrentIndex(model_index)

        self.temperature.setValue(snapshot.temperature)
        self.max_tokens.setValue(snapshot.max_tokens)
        self.history_messages.setValue(snapshot.history_messages)

        self.personality_text.setPlainText(snapshot.personality)
        self.personality_path.setText(
            f"Personality file: {snapshot.personality_path}"
        )

        self.memory_enabled.setChecked(snapshot.memory_enabled)
        self.automatic_extraction.setChecked(snapshot.automatic_extraction)
        self.retrieval_enabled.setChecked(snapshot.retrieval_enabled)

        self.embedding_model.clear()
        for model in snapshot.available_models:
            self.embedding_model.addItem(model, model)
        embedding_index = self.embedding_model.findData(snapshot.embedding_model)
        if embedding_index < 0:
            self.embedding_model.addItem(
                f"{snapshot.embedding_model} (not loaded)",
                snapshot.embedding_model,
            )
            embedding_index = self.embedding_model.count() - 1
        self.embedding_model.setCurrentIndex(embedding_index)

        self.minimum_confidence.setValue(snapshot.minimum_confidence)
        self.idle_delay.setValue(snapshot.idle_delay_seconds)
        self.jobs_per_cycle.setValue(snapshot.max_jobs_per_idle_cycle)
        self.semantic_threshold.setValue(snapshot.semantic_threshold)
        self.retrieval_limit.setValue(snapshot.retrieval_limit)
        self.retrieval_characters.setValue(snapshot.retrieval_max_characters)
        self.offline_mode.setChecked(snapshot.offline_mode)

        self._loading = False
        self._dirty = False
        self.status_label.setText("Settings loaded from local configuration.")
        self.save_button.setEnabled(False)
        self._update_memory_controls()

    def _update_memory_controls(self, *_args) -> None:
        enabled = self.memory_enabled.isChecked()
        for widget in (
            self.automatic_extraction,
            self.retrieval_enabled,
            self.embedding_model,
            self.minimum_confidence,
            self.idle_delay,
            self.jobs_per_cycle,
            self.semantic_threshold,
            self.retrieval_limit,
            self.retrieval_characters,
        ):
            widget.setEnabled(enabled)

        retrieval = enabled and self.retrieval_enabled.isChecked()
        self.embedding_model.setEnabled(retrieval)
        self.semantic_threshold.setEnabled(retrieval)
        self.retrieval_limit.setEnabled(retrieval)
        self.retrieval_characters.setEnabled(retrieval)

    def _mark_dirty(self, *_args) -> None:
        if self._loading or self._snapshot is None:
            return
        self._dirty = True
        self.status_label.setText("Unsaved changes")
        self.save_button.setEnabled(not self._saving)

    def _settings_values(self) -> dict:
        return {
            "model": str(self.chat_model.currentData()),
            "temperature": self.temperature.value(),
            "max_tokens": self.max_tokens.value(),
            "history_messages": self.history_messages.value(),
            "offline_mode": self.offline_mode.isChecked(),
            "memory_enabled": self.memory_enabled.isChecked(),
            "automatic_extraction": self.automatic_extraction.isChecked(),
            "retrieval_enabled": self.retrieval_enabled.isChecked(),
            "embedding_model": str(self.embedding_model.currentData()),
            "minimum_confidence": self.minimum_confidence.value(),
            "idle_delay_seconds": self.idle_delay.value(),
            "max_jobs_per_idle_cycle": self.jobs_per_cycle.value(),
            "semantic_threshold": self.semantic_threshold.value(),
            "retrieval_limit": self.retrieval_limit.value(),
            "retrieval_max_characters": self.retrieval_characters.value(),
        }

    def _save(self) -> None:
        if self._snapshot is None or self._saving or not self._dirty:
            return

        personality = self.personality_text.toPlainText()
        if not personality.strip():
            QMessageBox.warning(
                self,
                "Personality required",
                "V's personality instructions cannot be empty.",
            )
            return

        values = self._settings_values()
        if (
            values["memory_enabled"]
            and values["retrieval_enabled"]
            and values["model"] == values["embedding_model"]
        ):
            QMessageBox.warning(
                self,
                "Choose separate models",
                "The chat model and embedding model must be different.",
            )
            return

        self._saving = True
        self.save_button.setEnabled(False)
        self.status_label.setText("Saving local settings…")
        self.save_requested.emit(values, personality)

    def on_saved(self, message: str) -> None:
        self._saving = False
        self._dirty = False
        self.status_label.setText(message)
        self.save_button.setEnabled(False)

    def on_save_failed(self, message: str) -> None:
        self._saving = False
        self._dirty = True
        self.status_label.setText("Settings could not be saved.")
        self.save_button.setEnabled(True)
        QMessageBox.warning(self, "Settings could not be saved", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._dirty or self._saving:
            answer = QMessageBox.question(
                self,
                "Discard unsaved settings?",
                "Close Settings and discard unsaved changes?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        event.accept()
