import tempfile
import unittest

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from v.vision.image import prepare_image_file, prepare_qimage


class VisionImagePreparationTests(unittest.TestCase):
    def _write_png(self, path: Path, width: int = 32, height: int = 24):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(0x336699)
        self.assertTrue(image.save(str(path), "PNG"))

    def test_normalizes_supported_image_to_jpeg_in_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.png"
            self._write_png(path)
            original = path.read_bytes()

            data, mime_type = prepare_image_file(path)

            self.assertEqual(mime_type, "image/jpeg")
            self.assertTrue(data.startswith(b"\xff\xd8"))
            self.assertEqual(path.read_bytes(), original)

    def test_normalizes_camera_qimage_without_disk_io(self):
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill(0x336699)

        data, mime_type = prepare_qimage(image)

        self.assertEqual(mime_type, "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_rejects_non_image_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "not-image.bin"
            path.write_bytes(b"not an image")
            with self.assertRaisesRegex(ValueError, "supported image"):
                prepare_image_file(path)

    def test_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "empty.png"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "empty"):
                prepare_image_file(path)


if __name__ == "__main__":
    unittest.main()
