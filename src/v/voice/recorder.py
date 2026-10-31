"""Explicit push-to-talk microphone capture using Qt Multimedia."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import (
    QAudioDevice,
    QAudioFormat,
    QAudioSource,
    QMediaDevices,
)

from v.voice.audio import pcm_to_wav_16khz_mono


def _sample_format_name(sample_format: QAudioFormat.SampleFormat) -> str:
    mapping = {
        QAudioFormat.SampleFormat.UInt8: "UInt8",
        QAudioFormat.SampleFormat.Int16: "Int16",
        QAudioFormat.SampleFormat.Int32: "Int32",
        QAudioFormat.SampleFormat.Float: "Float",
    }
    try:
        return mapping[sample_format]
    except KeyError as error:
        raise ValueError(
            f"Unsupported Qt audio sample format: {sample_format!r}"
        ) from error


def _sample_width(sample_format: QAudioFormat.SampleFormat) -> int:
    return {
        QAudioFormat.SampleFormat.UInt8: 1,
        QAudioFormat.SampleFormat.Int16: 2,
        QAudioFormat.SampleFormat.Int32: 4,
        QAudioFormat.SampleFormat.Float: 4,
    }[sample_format]


class PushToTalkRecorder(QObject):
    """Capture into memory only; start is called by an explicit user action."""

    recording_started = Signal()
    recording_finished = Signal(bytes)
    recording_failed = Signal(str)
    recording_stopped = Signal(str)

    def __init__(
        self,
        *,
        device_id: str = "",
        max_seconds: int = 30,
        minimum_speech_ms: int = 250,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not 5 <= max_seconds <= 120:
            raise ValueError("Maximum recording duration must be 5–120 seconds.")
        if not 50 <= minimum_speech_ms <= 2000:
            raise ValueError("Minimum speech duration must be 50–2000 ms.")

        self.device_id = device_id
        self.max_seconds = max_seconds
        self.minimum_speech_ms = minimum_speech_ms

        self._source: QAudioSource | None = None
        self._device = None
        self._raw = bytearray()
        self._sample_rate = 0
        self._channels = 0
        self._sample_format = QAudioFormat.SampleFormat.Unknown
        self._active = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_max_duration)

    @property
    def is_recording(self) -> bool:
        return self._active

    def _resolve_input_device(self) -> QAudioDevice:
        devices = QMediaDevices.audioInputs()
        if self.device_id:
            for device in devices:
                if bytes(device.id()).hex() == self.device_id.casefold():
                    return device
            raise RuntimeError(
                "The selected microphone is unavailable. Refresh audio devices in Settings."
            )

        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise RuntimeError(
                "No microphone is available. Connect an input device and refresh Settings."
            )
        return device

    def start(self) -> None:
        """Open the selected microphone only when the user presses Hold to Talk."""
        if self._active:
            raise RuntimeError("Microphone capture is already active.")

        device = self._resolve_input_device()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(16000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        if not device.isFormatSupported(audio_format):
            audio_format = device.preferredFormat()
            if audio_format.sampleFormat() == QAudioFormat.SampleFormat.Unknown:
                raise RuntimeError("The selected microphone reports an unknown audio format.")

        sample_rate = audio_format.sampleRate()
        channels = audio_format.channelCount()
        sample_format = audio_format.sampleFormat()
        if not 8000 <= sample_rate <= 192000 or not 1 <= channels <= 8:
            raise RuntimeError("The microphone's preferred format is unsupported.")

        source = QAudioSource(device, audio_format, self)
        source.setBufferSize(
            min(
                sample_rate * channels * _sample_width(sample_format),
                1024 * 1024,
            )
        )
        io_device = source.start()
        if io_device is None:
            source.deleteLater()
            raise RuntimeError("Qt could not open the microphone input stream.")

        self._source = source
        self._device = io_device
        self._raw.clear()
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_format = sample_format
        self._active = True
        io_device.readyRead.connect(self._read_available)
        source.stateChanged.connect(self._on_source_state_changed)
        self._timer.start(self.max_seconds * 1000)
        self.recording_started.emit()

    def _read_available(self) -> None:
        if not self._active or self._device is None:
            return
        try:
            chunk = bytes(self._device.readAll())
        except (RuntimeError, TypeError) as error:
            self._fail(f"Could not read microphone data: {error}")
            return

        if not chunk:
            return

        maximum = (
            self._sample_rate
            * self._channels
            * _sample_width(self._sample_format)
            * self.max_seconds
        )
        if len(self._raw) + len(chunk) > maximum:
            remaining = max(0, maximum - len(self._raw))
            self._raw.extend(chunk[:remaining])
            self.stop()
            return

        self._raw.extend(chunk)

    def _on_source_state_changed(self, _state) -> None:
        if not self._active or self._source is None:
            return
        if self._source.error() != QAudioSource.Error.NoError:
            self._fail(f"Microphone capture error: {self._source.error()}")

    def _on_max_duration(self) -> None:
        if self._active:
            self.stop()

    def _fail(self, message: str) -> None:
        self._cleanup()
        self.recording_failed.emit(message)

    def stop(self) -> None:
        if not self._active:
            return

        self._read_available()
        if not self._active:
            return

        raw = bytes(self._raw)
        sample_rate = self._sample_rate
        channels = self._channels
        sample_format = _sample_format_name(self._sample_format)
        bytes_per_sample = _sample_width(self._sample_format)
        self._cleanup()

        try:
            minimum_samples = max(1, round(sample_rate * self.minimum_speech_ms / 1000))
            if len(raw) < minimum_samples * channels * bytes_per_sample:
                raise ValueError("No speech detected; the recording was too short.")

            wav_data = pcm_to_wav_16khz_mono(
                raw,
                sample_rate=sample_rate,
                channels=channels,
                sample_format=sample_format,
                max_seconds=self.max_seconds,
            )
        except (ValueError, TypeError) as error:
            self.recording_failed.emit(str(error))
            return

        self.recording_finished.emit(wav_data)
        self.recording_stopped.emit("Recording captured in memory; no file was written.")

    def cancel(self) -> None:
        if not self._active:
            return
        self._cleanup()
        self.recording_stopped.emit("Microphone capture cancelled; audio discarded.")

    def _cleanup(self) -> None:
        self._timer.stop()
        source, self._source = self._source, None
        self._device = None
        self._active = False
        if source is not None:
            source.stop()
            source.deleteLater()
        self._raw.clear()
        self._sample_rate = 0
        self._channels = 0
        self._sample_format = QAudioFormat.SampleFormat.Unknown
