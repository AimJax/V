"""Modality-neutral interaction events with explicit provenance.

Events carry references and derived text, never raw audio or image bytes. Capture
and receipt timestamps are timezone-aware so downstream memory can distinguish
what was observed from when V received it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping
from uuid import uuid4


class InteractionModality(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    CAMERA = "camera"
    SYSTEM = "system"


class InteractionEventKind(StrEnum):
    USER_MESSAGE = "user_message"
    SPEECH_TRANSCRIPT = "speech_transcript"
    IMAGE_OBSERVATION = "image_observation"
    CAMERA_SNAPSHOT = "camera_snapshot"
    AUDIO_PLAYBACK_STARTED = "audio_playback_started"
    AUDIO_PLAYBACK_FINISHED = "audio_playback_finished"
    INTERRUPTION = "interruption"
    CANCELLATION = "cancellation"
    TIMEOUT = "timeout"
    SENSOR_STATE_CHANGED = "sensor_state_changed"


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime.")


@dataclass(frozen=True, slots=True)
class InteractionEvent:
    """A provenance record for one interaction or modality lifecycle event.

    `occurred_at` is when the source event/capture happened; `received_at`
    is when local processing delivered the derived interaction into chat. `activation_context` records the user
    consent/activation path (for example, "typed", "push_to_talk", or
    "user_uploaded"). `content` is derived text only, never raw media.
    """

    kind: InteractionEventKind
    modality: InteractionModality
    occurred_at: datetime
    received_at: datetime
    activation_context: str
    conversation_id: str | None = None
    content: str | None = None
    source_ref: str | None = None
    confidence: float | None = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _aware(self.occurred_at, "occurred_at")
        _aware(self.received_at, "received_at")
        if not self.activation_context.strip():
            raise ValueError("activation_context cannot be empty.")
        if self.conversation_id is not None and not self.conversation_id.strip():
            raise ValueError("conversation_id cannot be empty when provided.")
        if self.content is not None and not self.content.strip():
            raise ValueError("content cannot be empty when provided.")
        if self.source_ref is not None and not self.source_ref.strip():
            raise ValueError("source_ref cannot be empty when provided.")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty.")
        if self.received_at < self.occurred_at:
            raise ValueError("received_at cannot precede occurred_at.")

    @classmethod
    def now(
        cls,
        *,
        kind: InteractionEventKind,
        modality: InteractionModality,
        activation_context: str,
        conversation_id: str | None = None,
        content: str | None = None,
        source_ref: str | None = None,
        confidence: float | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> "InteractionEvent":
        """Create an event whose source and receipt times are the current UTC time."""
        timestamp = datetime.now(timezone.utc)
        return cls(
            kind=kind,
            modality=modality,
            occurred_at=timestamp,
            received_at=timestamp,
            activation_context=activation_context,
            conversation_id=conversation_id,
            content=content,
            source_ref=source_ref,
            confidence=confidence,
            metadata=metadata or {},
        )

    @property
    def is_derived_content(self) -> bool:
        """True for transcriptions and model-generated visual descriptions."""
        return self.kind in {
            InteractionEventKind.SPEECH_TRANSCRIPT,
            InteractionEventKind.IMAGE_OBSERVATION,
            InteractionEventKind.CAMERA_SNAPSHOT,
        }
