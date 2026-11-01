"""Memory data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Memory:
    id: str
    memory_type: str
    subject: str
    content: str
    memory_key: str | None
    provenance: str
    confidence: float
    importance: int
    source_conversation_id: str | None
    source_message_id: int | None
    source_created_at: str | None
    evidence: str | None
    created_at: str
    updated_at: str
    last_confirmed_at: str | None