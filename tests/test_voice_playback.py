from collections import deque
from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer

from v.voice.playback import SpeechPlayback


class FakeBuffer:
    def __init__(self, events):
        self.events = events

    def deleteLater(self):
        self.events.append("delete_buffer")


class FakePlayer:
    def __init__(self, events):
        self.events = events

    def stop(self):
        self.events.append("stop")

    def setSource(self, source):
        self.events.append(("set_source", source.isEmpty()))


class PlaybackHarness:
    _release_buffer = SpeechPlayback._release_buffer
    _on_media_status = SpeechPlayback._on_media_status
    stop = SpeechPlayback.stop

    def __init__(self, *, pending):
        self.events = []
        self._buffer = FakeBuffer(self.events)
        self._pending = deque(pending)
        self.player = FakePlayer(self.events)

    def _play_next(self):
        self.events.append("play_next")


def test_end_of_media_detaches_source_before_releasing_buffer_and_defers_next():
    playback = PlaybackHarness(pending=[b"RIFFnext"])
    scheduled = []

    class FakeTimer:
        @staticmethod
        def singleShot(milliseconds, callback):
            scheduled.append((milliseconds, callback))

    with patch("v.voice.playback.QTimer", FakeTimer):
        playback._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)

    assert playback.events == [
        "stop",
        ("set_source", True),
        "delete_buffer",
    ]
    assert scheduled == [(0, playback._play_next)]
    assert playback._buffer is None


def test_stop_detaches_source_before_releasing_buffer_and_clears_queue():
    playback = PlaybackHarness(pending=[b"RIFFnext"])

    playback.stop()

    assert playback.events == [
        "stop",
        ("set_source", True),
        "delete_buffer",
    ]
    assert not playback._pending
    assert playback._buffer is None
