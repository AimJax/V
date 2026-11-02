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
    evidence: str | None
    created_at: str
    updated_at: str
    last_confirmed_at: str | None
    source_created_at: str | None = None

@dataclass(frozen=True, slots=True)
class MemoryLink:
    """A traceable structural association between two memory records."""

    memory_a_id: str
    memory_b_id: str
    relation_type: str
    basis: str
    confidence: float
    created_at: str
