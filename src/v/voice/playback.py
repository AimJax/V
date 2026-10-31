"""In-memory Qt Multimedia playback for synthesized WAV responses."""

from __future__ import annotations

from PySide6.QtCore import QObject, QBuffer, QByteArray, QIODevice, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer


class SpeechPlayback(QObject):
    """Play one synthesized WAV from a memory buffer without creating a file."""

    playback_finished = Signal()
    playback_failed = Signal(str)

    def __init__(
        self,
        *,
        device_id: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self._buffer: QBuffer | None = None

        self.output = QAudioOutput(self)
        if device_id:
            selected = None
            for device in QMediaDevices.audioOutputs():
                if bytes(device.id()).hex() == device_id.casefold():
                    selected = device
                    break
            if selected is None:
                raise RuntimeError(
                    "The selected speaker is unavailable. Refresh audio devices in Settings."
                )
            self.output.setDevice(selected)

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_error)

    @property
    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def play(self, wav_data: bytes) -> None:
        if not isinstance(wav_data, bytes) or not wav_data.startswith(b"RIFF"):
            raise ValueError("Speech output must be a WAV byte sequence.")

        self.stop()
        buffer = QBuffer(self)
        buffer.setData(QByteArray(wav_data))
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            buffer.deleteLater()
            raise RuntimeError("Could not open the in-memory speech buffer.")

        self._buffer = buffer
        self.player.setSourceDevice(buffer, QUrl("memory://v-speech.wav"))
        self.player.play()

    def stop(self) -> None:
        self.player.stop()
        buffer, self._buffer = self._buffer, None
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop()
            self.playback_finished.emit()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.stop()
            self.playback_failed.emit("Qt Multimedia could not decode the synthesized WAV.")

    def _on_error(
        self,
        _error: QMediaPlayer.Error,
        message: str,
    ) -> None:
        self.stop()
        self.playback_failed.emit(message or "Speech playback failed.")

    def close(self) -> None:
        self.stop()
        self.player.deleteLater()
        self.output.deleteLater()
