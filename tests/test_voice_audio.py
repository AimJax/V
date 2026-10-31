import io
import struct
import unittest
import wave

from v.voice.audio import pcm_to_wav_16khz_mono


class AudioConversionTests(unittest.TestCase):
    def _read_wav(self, payload):
        with wave.open(io.BytesIO(payload), "rb") as reader:
            return (
                reader.getnchannels(),
                reader.getsampwidth(),
                reader.getframerate(),
                reader.getnframes(),
                reader.readframes(reader.getnframes()),
            )

    def test_converts_int16_mono_to_canonical_wav(self):
        raw = struct.pack("<4h", 0, 1000, -1000, 32767)
        wav_data = pcm_to_wav_16khz_mono(
            raw,
            sample_rate=16000,
            channels=1,
            sample_format="Int16",
        )

        channels, width, rate, frames, samples = self._read_wav(wav_data)
        self.assertEqual((channels, width, rate, frames), (1, 2, 16000, 4))
        self.assertEqual(struct.unpack("<4h", samples), (0, 1000, -1000, 32766))

    def test_downmixes_stereo_and_resamples_to_16khz(self):
        raw = struct.pack("<12h", 1000, 3000, -1000, 1000, 2000, 2000, 0, 0, 1500, 500, -500, 500)
        wav_data = pcm_to_wav_16khz_mono(
            raw,
            sample_rate=48000,
            channels=2,
            sample_format="Int16",
        )

        channels, width, rate, frames, samples = self._read_wav(wav_data)
        self.assertEqual((channels, width, rate, frames), (1, 2, 16000, 2))
        self.assertEqual(len(samples), 4)

    def test_converts_float32_input(self):
        raw = struct.pack("<3f", -1.0, 0.0, 1.0)
        wav_data = pcm_to_wav_16khz_mono(
            raw,
            sample_rate=16000,
            channels=1,
            sample_format="Float",
        )
        *_, samples = self._read_wav(wav_data)
        self.assertEqual(struct.unpack("<3h", samples), (-32767, 0, 32767))

    def test_rejects_unsupported_sample_format(self):
        with self.assertRaisesRegex(ValueError, "Unsupported audio sample format"):
            pcm_to_wav_16khz_mono(
                b"\x00\x00",
                sample_rate=16000,
                channels=1,
                sample_format="Planar",
            )

    def test_rejects_audio_longer_than_configured_limit(self):
        raw = struct.pack("<32000h", *([0] * 32000))
        with self.assertRaisesRegex(ValueError, "exceeds the 1-second limit"):
            pcm_to_wav_16khz_mono(
                raw,
                sample_rate=16000,
                channels=1,
                sample_format="Int16",
                max_seconds=1,
            )


if __name__ == "__main__":
    unittest.main()
