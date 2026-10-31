"""Local audio input/output device discovery through Qt Multimedia."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioDeviceOption:
    """Stable device identifier plus a user-readable description."""

    device_id: str
    description: str
    is_default: bool

    @property
    def label(self) -> str:
        suffix = " (System default)" if self.is_default else ""
        return f"{self.description}{suffix}"


def list_audio_devices(direction: str) -> list[AudioDeviceOption]:
    """Enumerate audio devices without opening or recording from them."""
    normalized = direction.strip().casefold()
    if normalized not in {"input", "output"}:
        raise ValueError("Audio direction must be 'input' or 'output'.")

    try:
        from PySide6.QtMultimedia import QMediaDevices

        devices = (
            QMediaDevices.audioInputs()
            if normalized == "input"
            else QMediaDevices.audioOutputs()
        )
    except (ImportError, RuntimeError):
        return []

    options: list[AudioDeviceOption] = []
    for device in devices:
        try:
            raw_id = bytes(device.id())
            description = str(device.description()).strip()
            if not description:
                description = "Unnamed audio device"
            options.append(
                AudioDeviceOption(
                    device_id=raw_id.hex(),
                    description=description,
                    is_default=bool(device.isDefault()),
                )
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue

    return options
