"""Explicit one-shot local camera capture with a visible preview."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtMultimedia import (
    QCamera,
    QImageCapture,
    QMediaCaptureSession,
    QMediaDevices,
)
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from v.vision.image import prepare_qimage


class CameraCaptureDialog(QDialog):
    """Capture one still frame only after the user opens and confirms the dialog."""

    image_captured = Signal(bytes)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("V — Camera snapshot")
        self.setModal(True)
        self.resize(760, 560)
        self.setMinimumSize(560, 420)

        devices = QMediaDevices.videoInputs()
        if not devices:
            raise RuntimeError("No camera is available on this PC.")
        device = QMediaDevices.defaultVideoInput()
        if device.isNull():
            device = devices[0]

        layout = QVBoxLayout(self)
        self.preview = QVideoWidget(self)
        self.preview.setMinimumSize(480, 300)
        layout.addWidget(self.preview, 1)

        self.status = QLabel(
            "Starting local camera preview. Capture is available only while this dialog is open."
        )
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "color: #f0d58a; background: #302b1d; padding: 8px; border-radius: 6px;"
        )
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.capture_button = QPushButton("Capture once")
        self.capture_button.setEnabled(False)
        self.capture_button.clicked.connect(self._capture_once)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.capture_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.camera = QCamera(device, self)
        self.capture = QImageCapture(self)
        self.session = QMediaCaptureSession(self)
        self.session.setCamera(self.camera)
        self.session.setImageCapture(self.capture)
        self.session.setVideoOutput(self.preview)

        self.capture.readyForCaptureChanged.connect(
            self.capture_button.setEnabled
        )
        self.camera.activeChanged.connect(self._on_camera_active)
        self.capture.imageCaptured.connect(self._on_image_captured)
        self.capture.errorOccurred.connect(self._on_capture_error)
        self.camera.errorOccurred.connect(self._on_camera_error)
        self.camera.start()

    def _on_camera_active(self, active: bool) -> None:
        if active:
            self.status.setText(
                "CAMERA ACTIVE — preview is local. Press Capture once to send a still image to V."
            )
        elif self.camera.error() == QCamera.Error.NoError:
            self.status.setText("Camera preview is inactive.")
        self.capture_button.setEnabled(
            active and self.capture.isReadyForCapture()
        )

    def _capture_once(self) -> None:
        if not self.capture.isReadyForCapture():
            self.status.setText("Camera is not ready. Wait for the preview, or cancel.")
            return
        self.capture_button.setEnabled(False)
        self.status.setText("Capturing one frame in memory…")
        self.capture.capture()

    def _on_image_captured(self, _request_id: int, image) -> None:
        try:
            image_data, _mime_type = prepare_qimage(image)
        except (RuntimeError, ValueError) as error:
            self.status.setText(f"Could not prepare camera image: {error}")
            self.capture_button.setEnabled(self.capture.isReadyForCapture())
            return
        self.image_captured.emit(image_data)
        self.accept()

    def _on_capture_error(self, _request_id, _error, message: str) -> None:
        self.status.setText(f"Camera capture failed: {message}")
        self.capture_button.setEnabled(self.capture.isReadyForCapture())

    def _on_camera_error(self, _error, message: str) -> None:
        self.status.setText(f"Camera unavailable: {message}")
        self.capture_button.setEnabled(False)

    def closeEvent(self, event) -> None:
        self.camera.stop()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self.camera.stop()
        super().done(result)
