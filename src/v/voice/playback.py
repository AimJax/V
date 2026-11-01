"""Queued in-memory Qt Multimedia playback for synthesized WAV responses."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QObject, QBuffer, QByteArray, QIODevice, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer


class SpeechPlayback(QObject):
    """Play a sequence of synthesized WAV chunks without writing audio to disk."""

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
        self._pending: deque[bytes] = deque()

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
        """Replace current playback with one WAV payload."""
        self.stop()
        self.enqueue(wav_data)

    def enqueue(self, wav_data: bytes) -> None:
        """Append one WAV payload; start it immediately when the player is idle."""
        if not isinstance(wav_data, bytes) or not wav_data.startswith(b"RIFF"):
            raise ValueError("Speech output must be a WAV byte sequence.")

        self._pending.append(wav_data)
        if self._buffer is None:
            self._play_next()

    def _play_next(self) -> None:
        if self._buffer is not None:
            return
        if not self._pending:
            self.playback_finished.emit()
            return

        buffer = QBuffer(self)
        buffer.setData(QByteArray(self._pending.popleft()))
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            buffer.deleteLater()
            self.playback_failed.emit("Could not open the in-memory speech buffer.")
            self._play_next()
            return

        self._buffer = buffer
        self.player.setSourceDevice(buffer, QUrl("memory://v-speech.wav"))
        self.player.play()

    def _release_buffer(self) -> None:
        buffer, self._buffer = self._buffer, None
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()

    def stop(self) -> None:
        """Stop the current segment and discard every queued segment."""
        self.player.stop()
        self._pending.clear()
        self._release_buffer()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._release_buffer()
            self._play_next()
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
