import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from v.interaction.events import (
    InteractionEvent,
    InteractionEventKind,
    InteractionModality,
)


class InteractionEventTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)

    def test_records_capture_and_receipt_times_separately(self):
        event = InteractionEvent(
            kind=InteractionEventKind.SPEECH_TRANSCRIPT,
            modality=InteractionModality.AUDIO,
            occurred_at=self.now,
            received_at=self.now + timedelta(seconds=2),
            activation_context="push_to_talk",
            conversation_id="conversation-1",
            content="Hello V",
            confidence=0.91,
        )
        self.assertEqual(event.occurred_at, self.now)
        self.assertEqual(event.received_at - event.occurred_at, timedelta(seconds=2))
        self.assertTrue(event.is_derived_content)

    def test_now_uses_aware_utc_timestamps_and_unique_ids(self):
        first = InteractionEvent.now(
            kind=InteractionEventKind.USER_MESSAGE,
            modality=InteractionModality.TEXT,
            activation_context="typed",
            content="Hello",
        )
        second = InteractionEvent.now(
            kind=InteractionEventKind.USER_MESSAGE,
            modality=InteractionModality.TEXT,
            activation_context="typed",
            content="Hello",
        )
        self.assertEqual(first.occurred_at.tzinfo, timezone.utc)
        self.assertEqual(first.received_at, first.occurred_at)
        self.assertNotEqual(first.event_id, second.event_id)

    def test_rejects_naive_timestamps(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            InteractionEvent(
                kind=InteractionEventKind.USER_MESSAGE,
                modality=InteractionModality.TEXT,
                occurred_at=datetime(2026, 11, 8),
                received_at=self.now,
                activation_context="typed",
                content="Hello",
            )

    def test_rejects_receipt_before_capture(self):
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            InteractionEvent(
                kind=InteractionEventKind.CAMERA_SNAPSHOT,
                modality=InteractionModality.CAMERA,
                occurred_at=self.now,
                received_at=self.now - timedelta(seconds=1),
                activation_context="user_requested_snapshot",
                source_ref="local-observation:1",
            )

    def test_rejects_invalid_confidence_and_empty_activation(self):
        base = {
            "kind": InteractionEventKind.SPEECH_TRANSCRIPT,
            "modality": InteractionModality.AUDIO,
            "occurred_at": self.now,
            "received_at": self.now,
            "activation_context": "push_to_talk",
            "content": "Hello",
        }
        with self.assertRaisesRegex(ValueError, "confidence"):
            InteractionEvent(**base, confidence=1.1)
        with self.assertRaisesRegex(ValueError, "activation_context"):
            InteractionEvent(**{**base, "activation_context": " "})

    def test_event_is_immutable(self):
        event = InteractionEvent.now(
            kind=InteractionEventKind.INTERRUPTION,
            modality=InteractionModality.SYSTEM,
            activation_context="user_stop",
        )
        with self.assertRaises(FrozenInstanceError):
            event.content = "changed"


if __name__ == "__main__":
    unittest.main()
