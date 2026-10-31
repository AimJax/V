"""Configurable local settings dialog for V's desktop application."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSignalBlocker, Signal
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from v.desktop.audio_devices import list_audio_devices
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
        self.resize(780, 720)
        self.setMinimumSize(420, 320)
        self.setSizeGripEnabled(True)
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
        self._add_scrollable_tab(general, "General")

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
        self._add_scrollable_tab(personality, "Personality")

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
        self._add_scrollable_tab(memory, "Memory")

        voice = QWidget()
        voice_layout = QVBoxLayout(voice)
        voice_form = QFormLayout()
        voice_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.voice_status = QLabel(
            "Voice setup only: this tab does not open the microphone or start an audio engine. "
            "Voice capture will remain inactive until the local engines are installed and validated."
        )
        self.voice_status.setObjectName("muted")
        self.voice_status.setWordWrap(True)
        voice_layout.addWidget(self.voice_status)

        self.input_device = QComboBox()
        self.output_device = QComboBox()
        self.refresh_audio_button = QPushButton("Refresh devices")
        self.refresh_audio_button.clicked.connect(self._refresh_audio_devices)
        self.audio_device_note = QLabel(
            "Audio devices have not been enumerated. Refreshing lists devices only; it does not open the microphone."
        )
        self.audio_device_note.setObjectName("muted")
        self.audio_device_note.setWordWrap(True)

        voice_form.addRow("Microphone", self.input_device)
        voice_form.addRow("Speaker / output", self.output_device)
        voice_form.addRow(self.refresh_audio_button)
        voice_form.addRow(self.audio_device_note)

        self.whisper_server_path = QLineEdit()
        self.whisper_model_path = QLineEdit()
        self.silero_vad_model_path = QLineEdit()
        self.kokoro_model_path = QLineEdit()
        self.kokoro_voices_path = QLineEdit()
        self._add_path_picker(
            voice_form,
            "Whisper server executable",
            self.whisper_server_path,
            "Executables (*.exe)",
        )
        self._add_path_picker(
            voice_form,
            "Whisper model (multilingual)",
            self.whisper_model_path,
            "Whisper models (*.bin)",
        )
        self._add_path_picker(
            voice_form,
            "Silero VAD model",
            self.silero_vad_model_path,
            "VAD models (*.bin)",
        )
        self._add_path_picker(
            voice_form,
            "Kokoro ONNX model",
            self.kokoro_model_path,
            "ONNX models (*.onnx)",
        )
        self._add_path_picker(
            voice_form,
            "Kokoro voices file",
            self.kokoro_voices_path,
            "Kokoro voice files (*.bin)",
        )

        self.stt_language = QComboBox()
        self.stt_language.addItem("Automatic detection", "auto")
        self.stt_language.addItem("English", "en")
        self.stt_language.addItem("Indonesian", "id")

        self.stt_threads = QSpinBox()
        self.stt_threads.setRange(1, 8)

        voice_form.addRow("Speech recognition language", self.stt_language)
        voice_form.addRow("Whisper CPU threads", self.stt_threads)

        self.vad_threshold = QDoubleSpinBox()
        self.vad_threshold.setRange(0.1, 0.95)
        self.vad_threshold.setDecimals(2)
        self.vad_threshold.setSingleStep(0.05)

        self.vad_min_speech = QSpinBox()
        self.vad_min_speech.setRange(50, 2000)
        self.vad_min_speech.setSuffix(" ms")

        self.vad_silence = QSpinBox()
        self.vad_silence.setRange(100, 3000)
        self.vad_silence.setSuffix(" ms")

        self.max_utterance = QSpinBox()
        self.max_utterance.setRange(5, 120)
        self.max_utterance.setSuffix(" s")

        voice_form.addRow("VAD speech threshold", self.vad_threshold)
        voice_form.addRow("Minimum speech duration", self.vad_min_speech)
        voice_form.addRow("Silence to end an utterance", self.vad_silence)
        voice_form.addRow("Maximum utterance duration", self.max_utterance)

        self.wake_phrase = QLineEdit()
        self.kokoro_voice = QLineEdit()
        self.kokoro_voice.setPlaceholderText("e.g. af_heart")
        self.tts_speed = QDoubleSpinBox()
        self.voice_enabled = QCheckBox(
            "Enable local voice interaction (push-to-talk)"
        )
        self.speak_replies = QCheckBox(
            "Speak V's replies using the selected Kokoro voice"
        )
        self.tts_speed.setRange(0.5, 1.5)
        self.tts_speed.setDecimals(2)
        self.tts_speed.setSingleStep(0.05)

        voice_form.addRow("Wake phrase (future stage)", self.wake_phrase)
        voice_form.addRow("Kokoro voice ID", self.kokoro_voice)
        voice_form.addRow("Speech rate", self.tts_speed)
        voice_form.addRow(self.voice_enabled)
        voice_form.addRow(self.speak_replies)
        voice_layout.addLayout(voice_form)

        voice_note = QLabel(
            "Audio format: 16 kHz mono. Whisper.cpp uses the Silero VAD model before transcription. "
            "Kokoro ONNX supports V's Python 3.13 environment; install the optional voice extra separately. "
            "The selected voice ID is provisional until local voice audition is implemented. "
            "Voice is disabled by default. When enabled, microphone capture starts only while you hold the Push to Talk button. Wake-word listening is not active yet."
        )
        voice_note.setObjectName("muted")
        voice_note.setWordWrap(True)
        voice_layout.addWidget(voice_note)
        voice_layout.addStretch(1)
        self._add_scrollable_tab(voice, "Voice")

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
        self._add_scrollable_tab(privacy, "Privacy")

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
        self.voice_enabled.toggled.connect(self._update_voice_controls)

    def showEvent(self, event: QShowEvent) -> None:
        """Keep the dialog within the usable screen area on scaled displays."""
        super().showEvent(event)
        screen = self.screen()
        if screen is None:
            return

        available = screen.availableGeometry()
        margin = 32
        max_width = max(420, available.width() - margin * 2)
        max_height = max(320, int(available.height() * 0.90))
        min_width = min(560, max_width)
        min_height = min(420, max_height)
        self.setMinimumSize(min_width, min_height)

        width = min(max(self.width(), min_width), max_width)
        height = min(max(self.height(), min_height), max_height)
        self.resize(width, height)

        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _add_scrollable_tab(self, page: QWidget, title: str) -> None:
        """Give each settings page its own scroll area while keeping the footer fixed."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)

    def _add_path_picker(
        self,
        form: QFormLayout,
        label: str,
        editor: QLineEdit,
        name_filter: str,
    ) -> None:
        row = QHBoxLayout()
        browse = QPushButton("Browse…")
        browse.clicked.connect(
            lambda _checked=False, field=editor, filter_text=name_filter:
                self._browse_path(field, filter_text)
        )
        row.addWidget(editor, 1)
        row.addWidget(browse)
        form.addRow(label, row)

    def _browse_path(self, editor: QLineEdit, name_filter: str) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select local voice asset",
            editor.text() or "",
            name_filter,
        )
        if path:
            editor.setText(path)

    def _populate_audio_devices(
        self,
        voice: dict,
        *,
        discover: bool = False,
    ) -> None:
        inputs = []
        outputs = []
        if discover:
            try:
                inputs = list_audio_devices("input")
                outputs = list_audio_devices("output")
            except (ImportError, RuntimeError, ValueError) as error:
                self.audio_device_note.setText(
                    f"Audio device enumeration failed: {error}"
                )
            else:
                self.audio_device_note.setText(
                    f"Detected {len(inputs)} microphone(s) and "
                    f"{len(outputs)} output device(s). "
                    "Enumeration does not open the microphone."
                )
        else:
            self.audio_device_note.setText(
                "Press Refresh devices to enumerate local audio hardware. "
                "This does not open or record from the microphone."
            )

        # Rebuilding the choices is initialization, not a user edit. Block
        # currentIndexChanged until the saved selections have been restored.
        blockers = [
            QSignalBlocker(self.input_device),
            QSignalBlocker(self.output_device),
        ]
        self.input_device.clear()
        self.output_device.clear()
        self.input_device.addItem("System default microphone", "")
        self.output_device.addItem("System default speaker", "")

        for device in inputs:
            self.input_device.addItem(device.label, device.device_id)
        for device in outputs:
            self.output_device.addItem(device.label, device.device_id)

        for combo, key in (
            (self.input_device, "input_device_id"),
            (self.output_device, "output_device_id"),
        ):
            selected_id = str(voice.get(key, "") or "")
            index = combo.findData(selected_id)
            if index < 0 and selected_id:
                combo.addItem(
                    f"Saved device unavailable ({selected_id[:16]}…)",
                    selected_id,
                )
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
        blockers.clear()

    def _refresh_audio_devices(self) -> None:
        voice = self._snapshot.voice if self._snapshot is not None else {}
        self._populate_audio_devices(voice, discover=True)

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
            self.input_device,
            self.output_device,
            self.stt_language,
            self.stt_threads,
            self.whisper_server_path,
            self.whisper_model_path,
            self.silero_vad_model_path,
            self.kokoro_model_path,
            self.kokoro_voices_path,
            self.vad_threshold,
            self.vad_min_speech,
            self.vad_silence,
            self.max_utterance,
            self.wake_phrase,
            self.kokoro_voice,
            self.tts_speed,
            self.voice_enabled,
            self.speak_replies,
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
            elif isinstance(widget, QLineEdit):
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

        voice = snapshot.voice
        self._populate_audio_devices(voice)
        self.whisper_server_path.setText(
            str(voice.get("whisper_server_path", ""))
        )
        self.whisper_model_path.setText(
            str(voice.get("whisper_model_path", ""))
        )
        self.silero_vad_model_path.setText(
            str(voice.get("silero_vad_model_path", ""))
        )
        self.kokoro_model_path.setText(
            str(voice.get("kokoro_model_path", ""))
        )
        self.kokoro_voices_path.setText(
            str(voice.get("kokoro_voices_path", ""))
        )
        self.stt_language.setCurrentIndex(
            max(
                0,
                self.stt_language.findData(
                    str(voice.get("stt_language", "auto"))
                ),
            )
        )
        self.stt_threads.setValue(int(voice.get("stt_threads", 4)))
        self.vad_threshold.setValue(float(voice.get("vad_threshold", 0.50)))
        self.vad_min_speech.setValue(
            int(voice.get("vad_min_speech_duration_ms", 250))
        )
        self.vad_silence.setValue(
            int(voice.get("vad_silence_duration_ms", 700))
        )
        self.max_utterance.setValue(
            int(voice.get("max_utterance_seconds", 30))
        )
        self.wake_phrase.setText(str(voice.get("wake_phrase", "Hey V")))
        self.kokoro_voice.setText(str(voice.get("kokoro_voice", "af_heart")))
        self.tts_speed.setValue(float(voice.get("tts_speed", 1.0)))
        self.voice_enabled.setChecked(bool(voice.get("enabled", False)))
        self.speak_replies.setChecked(bool(voice.get("speak_replies", False)))

        self._loading = False
        self._dirty = False
        self.status_label.setText("Settings loaded from local configuration.")
        self.save_button.setEnabled(False)
        self._update_memory_controls()
        self._update_voice_controls()

    def _update_voice_controls(self, *_args) -> None:
        enabled = self.voice_enabled.isChecked()
        self.speak_replies.setEnabled(enabled)
        if not enabled and self.speak_replies.isChecked():
            self.speak_replies.setChecked(False)

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
            "voice_wake_phrase": self.wake_phrase.text().strip(),
            "voice_input_device_id": str(
                self.input_device.currentData() or ""
            ),
            "voice_output_device_id": str(
                self.output_device.currentData() or ""
            ),
            "voice_sample_rate": int(
                self._snapshot.voice.get("sample_rate", 16000)
            ),
            "voice_stt_language": str(self.stt_language.currentData()),
            "voice_stt_threads": self.stt_threads.value(),
            "voice_whisper_server_path": self.whisper_server_path.text().strip(),
            "voice_whisper_model_path": self.whisper_model_path.text().strip(),
            "voice_silero_vad_model_path": self.silero_vad_model_path.text().strip(),
            "voice_vad_threshold": self.vad_threshold.value(),
            "voice_vad_min_speech_duration_ms": self.vad_min_speech.value(),
            "voice_vad_silence_duration_ms": self.vad_silence.value(),
            "voice_max_utterance_seconds": self.max_utterance.value(),
            "voice_kokoro_model_path": self.kokoro_model_path.text().strip(),
            "voice_kokoro_voices_path": self.kokoro_voices_path.text().strip(),
            "voice_kokoro_voice": self.kokoro_voice.text().strip(),
            "voice_tts_speed": self.tts_speed.value(),
            "voice_enabled": self.voice_enabled.isChecked(),
            "voice_speak_replies": self.speak_replies.isChecked(),
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
