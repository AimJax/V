import io
import unittest
import wave

os_import = None

from PySide6.QtCore import QCoreApplication
from PySide6.QtMultimedia import QAudioFormat, QMediaDevices

from unittest.mock import Mock, patch

from v.voice.recorder import PushToTalkRecorder


class PushToTalkRecorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def _fake_source(self):
        source = Mock()
        source.stop = Mock()
        source.deleteLater = Mock()
        return source

    def test_construction_does_not_enumerate_audio_devices(self):
        with patch.object(QMediaDevices, "audioInputs") as inputs:
            recorder = PushToTalkRecorder()
        inputs.assert_not_called()
        self.assertFalse(recorder.is_recording)
        recorder.deleteLater()

    def test_stop_packages_in_memory_wav_and_cleans_capture_state(self):
        recorder = PushToTalkRecorder(max_seconds=5)
        source = self._fake_source()
        device = Mock()
        device.readAll.return_value = b""
        recorder._source = source
        recorder._device = device
        recorder._sample_rate = 16000
        recorder._channels = 1
        recorder._sample_format = QAudioFormat.SampleFormat.Int16
        recorder._raw.extend(b"\x00\x00" * 8000)
        recorder._active = True
        received = []
        recorder.recording_finished.connect(received.append)

        recorder.stop()

        self.assertFalse(recorder.is_recording)
        self.assertEqual(len(received), 1)
        with wave.open(io.BytesIO(received[0]), "rb") as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getnframes(), 8000)
        source.stop.assert_called_once()
        source.deleteLater.assert_called_once()

    def test_duration_overflow_stops_without_recursive_read(self):
        recorder = PushToTalkRecorder(max_seconds=5)
        source = self._fake_source()
        device = Mock()
        device.readAll.return_value = b"\x01\x00" * 100
        recorder._source = source
        recorder._device = device
        recorder._sample_rate = 16000
        recorder._channels = 1
        recorder._sample_format = QAudioFormat.SampleFormat.Int16
        maximum_bytes = 16000 * 5 * 2
        recorder._raw.extend(b"\x00" * (maximum_bytes - 2))
        recorder._active = True
        finished = []
        recorder.recording_finished.connect(finished.append)

        recorder._read_available()

        self.assertFalse(recorder.is_recording)
        self.assertEqual(len(finished), 1)
        self.assertEqual(device.readAll.call_count, 1)
        source.stop.assert_called_once()

    def test_cancel_discards_audio_without_emitting_recording(self):
        recorder = PushToTalkRecorder()
        source = self._fake_source()
        recorder._source = source
        recorder._device = Mock()
        recorder._sample_rate = 16000
        recorder._channels = 1
        recorder._sample_format = QAudioFormat.SampleFormat.Int16
        recorder._raw.extend(b"\x00\x00" * 1000)
        recorder._active = True
        finished = []
        stopped = []
        recorder.recording_finished.connect(finished.append)
        recorder.recording_stopped.connect(stopped.append)

        recorder.cancel()

        self.assertFalse(recorder.is_recording)
        self.assertEqual(finished, [])
        self.assertEqual(len(stopped), 1)
        self.assertEqual(len(recorder._raw), 0)
        source.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
