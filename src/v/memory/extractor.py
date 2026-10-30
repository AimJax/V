"""Conservative local-LLM memory extraction."""

from __future__ import annotations

import json
import math
import re

from dataclasses import dataclass

from v.conversations.store import ConversationStore
from v.memory.queue import ExtractionQueue
from v.memory.store import MEMORY_TYPES, MemoryStore
from v.providers.base import ChatMessage, ChatProvider


EXTRACTION_SYSTEM_PROMPT = """
You are V's long-term memory extraction component.

Your task is to identify durable, useful information that the USER
explicitly stated about themselves in the supplied messages.

Only extract information that is likely to be useful in future conversations:
- Stable personal profile facts the user explicitly stated.
- Preferences and dislikes.
- Ongoing projects, goals, and learning activities.
- Important relationships the user explicitly described.
- Significant personal events worth remembering.

Do NOT extract:
- Casual greetings, small talk, weather, or temporary circumstances.
- Hypothetical statements, wishes, questions, roleplay, fiction, or quotes
  attributed to somebody else.
- Claims made by the assistant.
- Guesses about personality, emotions, intentions, or habits.
- Information that is not explicitly asserted as true by the user.
- Passwords, authentication tokens, API keys, secrets, or security answers.
- Phone numbers, email addresses, exact home/work addresses, government IDs,
  financial account details, or payment-card information.
- Health diagnoses, medical details, religious beliefs, political affiliation,
  sexual orientation or sex-life details, race, ethnicity, criminal history,
  or trade-union membership.

Be conservative. Returning no memory is better than storing a guess.

For every proposed memory:
- source_message_id must identify the exact supplied user message.
- evidence must be a verbatim excerpt from that message.
- content must preserve what the user actually asserted.
- provenance must always be "explicit".
- confidence must reflect extraction certainty.
- memory_key must be a stable, concise, unique key when possible.
- memory_type must be one of:
  profile, preference, episodic, relationship, project, fact.
- importance must be an integer from 1 to 5.
- Use importance 3 or higher only for information genuinely worth retaining.
- Never turn a temporary statement into a permanent profile fact.

Return ONLY valid JSON. No Markdown fences or explanatory text.

Exact output structure:
{
  "memories": [
    {
      "source_message_id": 123,
      "memory_type": "profile",
      "subject": "User",
      "content": "The user's name is Example User.",
      "memory_key": "user.name",
      "provenance": "explicit",
      "confidence": 0.99,
      "importance": 5,
      "evidence": "I'm Example User"
    }
  ]
}

If there are no useful memories, return:
{"memories":[]}
""".strip()


SENSITIVE_TERMS = (
    "password",
    "passcode",
    "api key",
    "secret key",
    "recovery phrase",
    "security answer",
    "medical diagnosis",
    "diagnosis",
    "medication",
    "prescription",
    "mental health condition",
    "religious belief",
    "religion",
    "muslim",
    "christian",
    "hindu",
    "buddhist",
    "atheist",
    "political affiliation",
    "political party",
    "sexual orientation",
    "sex life",
    "ethnicity",
    "racial identity",
    "criminal record",
    "criminal history",
    "trade union membership",
    "bank account",
    "credit card",
    "passport number",
    "national id",
    "social security",
    "home address",
)

EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)

SECRET_PATTERN = re.compile(
    r"\b(password|passcode|api[_ -]?key|secret[_ -]?key|"
    r"bearer\s+[A-Za-z0-9._~-]{8,})\b",
    re.IGNORECASE,
)

LONG_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{13,19}(?!\d)")


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    jobs_completed: int = 0
    jobs_failed: int = 0
    memories_created: int = 0
    candidates_skipped: int = 0


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _contains_sensitive_content(*values: str) -> bool:
    combined = " ".join(values).casefold()

    if any(term in combined for term in SENSITIVE_TERMS):
        return True

    if EMAIL_PATTERN.search(combined):
        return True

    if SECRET_PATTERN.search(combined):
        return True

    if LONG_NUMBER_PATTERN.search(combined):
        return True

    return False


def _parse_response(raw: str) -> list[dict]:
    """Parse JSON, tolerating a surrounding Markdown code fence."""
    content = raw.strip()

    if content.startswith("```"):
        content = re.sub(
            r"^```(?:json)?\s*",
            "",
            content,
            count=1,
            flags=re.IGNORECASE,
        )
        content = re.sub(r"\s*```$", "", content, count=1)

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)

        if match is None:
            raise ValueError("The model did not return valid JSON.")

        payload = json.loads(match.group(0))

    if not isinstance(payload, dict):
        raise ValueError("Extraction response must be a JSON object.")

    memories = payload.get("memories")

    if not isinstance(memories, list):
        raise ValueError("Extraction response has no memories array.")

    if not all(isinstance(item, dict) for item in memories):
        raise ValueError("Every memory candidate must be a JSON object.")

    return memories


class MemoryExtractor:
    """Extract and validate explicit memories using a local chat provider."""

    def __init__(
        self,
        provider: ChatProvider,
        conversation_store: ConversationStore,
        memory_store: MemoryStore,
        queue: ExtractionQueue,
        *,
        min_confidence: float = 0.90,
    ) -> None:
        if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1.")

        self.provider = provider
        self.conversation_store = conversation_store
        self.memory_store = memory_store
        self.queue = queue
        self.min_confidence = min_confidence

    async def process_pending(self, limit: int = 5) -> ExtractionReport:
        jobs = self.queue.list_pending(limit=limit)

        if not jobs:
            return ExtractionReport()

        source_messages = {}

        for job in jobs:
            message_id = job["source_message_id"]
            message = self.conversation_store.get_message_record(message_id)

            if (
                message is None
                or message.role != "user"
                or message.conversation_id != job["conversation_id"]
            ):
                self.queue.complete(message_id)
                continue

            source_messages[message_id] = message

        if not source_messages:
            return ExtractionReport(jobs_completed=len(jobs))

        source_payload = [
            {
                "source_message_id": message_id,
                "user_message": message.content,
            }
            for message_id, message in source_messages.items()
        ]

        try:
            result = await self.provider.chat(
                [
                    ChatMessage(
                        role="system",
                        content=EXTRACTION_SYSTEM_PROMPT,
                    ),
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            source_payload,
                            ensure_ascii=False,
                        ),
                    ),
                ],
                temperature=0.1,
                max_tokens=800,
            )

            candidates = _parse_response(result.content)

        except Exception as error:
            for message_id in source_messages:
                self.queue.fail(message_id, str(error))

            return ExtractionReport(
                jobs_failed=len(source_messages),
            )

        created = 0
        skipped = 0

        for candidate in candidates:
            message_id = candidate.get("source_message_id")

            if (
                isinstance(message_id, bool)
                or not isinstance(message_id, int)
                or message_id not in source_messages
            ):
                skipped += 1
                continue

            source = source_messages[message_id].content

            memory_type = candidate.get("memory_type")
            subject = candidate.get("subject")
            content = candidate.get("content")
            memory_key = candidate.get("memory_key")
            provenance = candidate.get("provenance")
            evidence = candidate.get("evidence")
            confidence = candidate.get("confidence")
            importance = candidate.get("importance")

            if (
                memory_type not in MEMORY_TYPES
                or memory_type == "inferred_pattern"
                or provenance != "explicit"
                or not isinstance(subject, str)
                or not subject.strip()
                or not isinstance(content, str)
                or not content.strip()
                or not isinstance(memory_key, str)
                or not memory_key.strip()
                or len(memory_key) > 160
                or not isinstance(evidence, str)
                or not evidence.strip()
            ):
                skipped += 1
                continue

            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence)
                or confidence < self.min_confidence
            ):
                skipped += 1
                continue

            if (
                isinstance(importance, bool)
                or not isinstance(importance, int)
                or not 3 <= importance <= 5
            ):
                skipped += 1
                continue

            normalized_source = _normalize_text(source)
            normalized_evidence = _normalize_text(evidence)

            if (
                len(normalized_evidence) < 6
                or normalized_evidence not in normalized_source
            ):
                skipped += 1
                continue

            if _contains_sensitive_content(
                source,
                evidence,
                content,
                subject,
            ):
                skipped += 1
                continue

            try:
                self.memory_store.create_memory(
                    content=evidence.strip(),
                    memory_type=memory_type,
                    subject=subject,
                    memory_key=memory_key,
                    provenance="explicit",
                    confidence=float(confidence),
                    importance=importance,
                    source_conversation_id=(
                        source_messages[message_id].conversation_id
                    ),
                    source_message_id=message_id,
                    evidence=evidence,
                )
                created += 1

            except (ValueError, TypeError):
                # A duplicate key or invalid candidate is not allowed
                # to overwrite an existing memory.
                skipped += 1

        for message_id in source_messages:
            self.queue.complete(message_id)

        return ExtractionReport(
            jobs_completed=len(source_messages),
            memories_created=created,
            candidates_skipped=skipped,
        )