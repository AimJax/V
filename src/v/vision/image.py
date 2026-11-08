"""Validate and normalize user-selected images entirely in memory."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImageReader


MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_EDGE = 2048



def prepare_qimage(image) -> tuple[bytes, str]:
    """Bound and JPEG-encode a captured Qt image without writing it to disk."""
    if image is None or image.isNull():
        raise ValueError("The captured camera image is empty.")
    if image.width() * image.height() > MAX_IMAGE_PIXELS:
        raise ValueError("The captured image exceeds the 25-megapixel limit.")
    if image.width() > MAX_IMAGE_EDGE or image.height() > MAX_IMAGE_EDGE:
        image = image.scaled(
            MAX_IMAGE_EDGE,
            MAX_IMAGE_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    output = QByteArray()
    output_buffer = QBuffer(output)
    if not output_buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Could not create the camera image buffer.")
    if not image.save(output_buffer, "JPEG", 88):
        output_buffer.close()
        raise RuntimeError("Could not normalize the camera image.")
    output_buffer.close()
    return bytes(output), "image/jpeg"


def prepare_image_file(path: str | Path) -> tuple[bytes, str]:
    """Decode, bound, and JPEG-normalize a user-selected image in memory.

    The original file is never modified. The returned bytes are transient and
    intended only for the explicitly requested local vision inference call.
    """
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError("The selected image file no longer exists.")
    size = source.stat().st_size
    if size < 1:
        raise ValueError("The selected image file is empty.")
    if size > MAX_SOURCE_BYTES:
        raise ValueError("Images larger than 20 MiB are not supported.")

    source_bytes = source.read_bytes()
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise ValueError("Images larger than 20 MiB are not supported.")
    buffer = QBuffer()
    buffer.setData(QByteArray(source_bytes))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ValueError("Could not read the selected image in memory.")

    reader = QImageReader(buffer)
    reader.setDecideFormatFromContent(True)
    image_size = reader.size()
    if not image_size.isValid() or image_size.width() < 1 or image_size.height() < 1:
        raise ValueError("The selected file is not a supported image.")
    if image_size.width() * image_size.height() > MAX_IMAGE_PIXELS:
        raise ValueError("Images larger than 25 megapixels are not supported.")

    image_format = bytes(reader.format()).decode("ascii", errors="ignore").casefold()
    if image_format not in {"jpg", "jpeg", "png", "webp"}:
        raise ValueError("Supported image formats are JPEG, PNG, and WebP.")

    reader.setAutoTransform(True)
    image = reader.read()
    buffer.close()
    if image.isNull():
        raise ValueError(f"Could not decode the selected image: {reader.errorString()}")

    if image.width() > MAX_IMAGE_EDGE or image.height() > MAX_IMAGE_EDGE:
        image = image.scaled(
            MAX_IMAGE_EDGE,
            MAX_IMAGE_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    output = QByteArray()
    output_buffer = QBuffer(output)
    if not output_buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Could not create the normalized image buffer.")
    if not image.save(output_buffer, "JPEG", 88):
        output_buffer.close()
        raise RuntimeError("Could not normalize the selected image.")
    output_buffer.close()
    return bytes(output), "image/jpeg"
