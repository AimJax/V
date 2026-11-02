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
- Ongoing or materially relevant current circumstances, even when they may change:
  work conditions, living arrangements, family responsibilities, financial pressures,
  practical constraints, sustained difficulties, and plans that affect future advice.
  Store these as episodic/current-context memories rather than permanent profile facts.
- The concrete circumstances behind a user's venting when those circumstances are
  ongoing and useful for continuity. Preserve the facts and context, not the raw rant
  or a guessed emotional diagnosis.

Do NOT extract:
- Casual greetings, small talk, weather, or fleeting one-off circumstances that have
  no likely value after the immediate conversation.
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
- evidence must be a verbatim excerpt from that message, no more than 600 characters.
- Choose a concise quotation that directly supports the memory, rather than copying
  the whole message or an entire extraction window.
- content must preserve what the user actually asserted.
- provenance must always be "explicit".
- confidence must reflect extraction certainty.
- memory_key must be a stable, concise, unique key when possible.
- subject must be a concise, canonical name for the person, project, or topic the memory concerns.
  Reuse the same subject label for later statements about the same named project or entity.
  Prefer the actual project/entity name (for example, "Project V") over a vague
  label such as "User" when the statement is specifically about that project.
- memory_type must be one of:
  profile, preference, episodic, relationship, project, fact.
- importance must be an integer from 1 to 5.
- Use importance 3 or higher only for information genuinely worth retaining.
- Each source user message may include a small surrounding conversation context.
  Use that context only to understand references, chronology, and what the user is responding to.
  Context messages are not source statements and must never be used as evidence.
  Never attribute an assistant's words, suggestions, or assumptions to the user.
  Every candidate's evidence must be an exact quotation from that candidate's own
  `user_message`, not from surrounding context.
  The source message itself must contain enough of the user's assertion to support
  the proposed memory. If it only says "yes", "exactly", "that one", or otherwise
  depends entirely on another message for the underlying claim, return no memory
  for that source message. Do not convert an assistant suggestion into a user fact
  merely because the user is responding to it.
- Interpret each message using its supplied original timestamp, not the date of reprocessing.
- A statement such as "currently", "now", or "this year" describes the user's circumstances
  at the source message timestamp. Do not present old circumstances as current today.
- When a circumstance, preference, role, plan, or relationship changes over time,
  preserve distinct dated episodic snapshots rather than overwriting the earlier state.
  Episodic records may reuse a stable memory_key to form a timeline. Do not label an
  older snapshot as current merely because it was reprocessed later.
- If a date or timeframe is not explicit in the message, do not invent one.
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
    conflicts_queued: int = 0


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


def _split_text_windows(
    text: str,
    *,
    max_characters: int = 5000,
    overlap_characters: int = 250,
) -> list[str]:
    """Split a long message into bounded overlapping windows without losing text."""
    if max_characters < 100 or overlap_characters < 0:
        raise ValueError("Invalid long-message window settings.")
    if len(text) <= max_characters:
        return [text]

    windows: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_characters)
        end = hard_end

        if hard_end < len(text):
            floor = start + max_characters // 2
            boundaries = (
                text.rfind("\n\n", floor, hard_end),
                text.rfind("\n", floor, hard_end),
                text.rfind(". ", floor, hard_end),
                text.rfind("; ", floor, hard_end),
                text.rfind(" ", floor, hard_end),
            )
            boundary = max(boundaries)
            if boundary > floor:
                marker = text[boundary:boundary + 2]
                end = boundary + (2 if marker in {"\n\n", ". ", "; "} else 1)

        window = text[start:end]
        if window:
            windows.append(window)

        if end >= len(text):
            break

        start = max(start + 1, end - overlap_characters)

    return windows


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
        conflict_store=None,
    ) -> None:
        if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1.")

        self.provider = provider
        self.conversation_store = conversation_store
        self.memory_store = memory_store
        self.queue = queue
        self.min_confidence = min_confidence
        self.conflict_store = conflict_store

    async def extract_candidates(
        self,
        messages: list,
    ) -> tuple[list[dict], int]:
        """Extract and strictly validate proposals without writing memories.

        Long user messages are split into overlapping, bounded windows so one
        unusually large rant cannot exhaust the local model's context window.
        Every proposed quotation is still verified against the complete,
        original source message before it can become a memory.
        """
        source_messages = {
            message.id: message
            for message in messages
            if message.role == "user" and message.content.strip()
        }
        if not source_messages:
            return [], 0

        requests: list[dict] = []
        for message_id, message in source_messages.items():
            context_messages = self.conversation_store.get_surrounding_messages(
                message_id,
                before=1,
                after=1,
                max_chars_per_message=1200,
            )
            context_payload = [
                {
                    "message_id": item.id,
                    "role": item.role,
                    "created_at": item.created_at,
                    "content": item.content,
                }
                for item in context_messages
            ]
            for window_index, window in enumerate(
                _split_text_windows(message.content)
            ):
                requests.append(
                    {
                        "source_message_id": message_id,
                        "source_conversation_id": message.conversation_id,
                        "source_created_at": message.created_at,
                        "window_index": window_index,
                        "user_message": window,
                        "surrounding_context": context_payload,
                    }
                )

        # Keep each request small enough for local models with modest context
        # limits. Context is bounded separately from each source text window.
        request_groups: list[list[dict]] = []
        group: list[dict] = []
        group_characters = 0
        for entry in requests:
            entry_characters = (
                len(entry["user_message"])
                + sum(len(item["content"]) for item in entry["surrounding_context"])
            )
            if group and group_characters + entry_characters > 10000:
                request_groups.append(group)
                group = []
                group_characters = 0
            group.append(entry)
            group_characters += entry_characters
        if group:
            request_groups.append(group)

        raw_candidates: list[dict] = []
        for request_group in request_groups:
            result = await self.provider.chat(
                [
                    ChatMessage(role="system", content=EXTRACTION_SYSTEM_PROMPT),
                    ChatMessage(
                        role="user",
                        content=json.dumps(request_group, ensure_ascii=False),
                    ),
                ],
                temperature=0.1,
                max_tokens=1200,
            )
            raw_candidates.extend(_parse_response(result.content))

        validated: list[dict] = []
        skipped = 0
        seen_candidates: set[tuple[int, str, str]] = set()

        for candidate in raw_candidates:
            message_id = candidate.get("source_message_id")
            if (
                isinstance(message_id, bool)
                or not isinstance(message_id, int)
                or message_id not in source_messages
            ):
                skipped += 1
                continue

            source_message = source_messages[message_id]
            memory_type = candidate.get("memory_type")
            subject = candidate.get("subject")
            model_content = candidate.get("content")
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
                or not isinstance(model_content, str)
                or not model_content.strip()
                or not isinstance(memory_key, str)
                or not memory_key.strip()
                or len(memory_key) > 160
                or not isinstance(evidence, str)
                or not evidence.strip()
                or len(evidence.strip()) > 600
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

            normalized_source = _normalize_text(source_message.content)
            normalized_evidence = _normalize_text(evidence)
            if (
                len(normalized_evidence) < 6
                or normalized_evidence not in normalized_source
            ):
                skipped += 1
                continue

            if _contains_sensitive_content(
                source_message.content,
                evidence,
                model_content,
                subject,
            ):
                skipped += 1
                continue

            dedupe_key = (
                message_id,
                memory_key.strip().casefold(),
                normalized_evidence,
            )
            if dedupe_key in seen_candidates:
                skipped += 1
                continue
            seen_candidates.add(dedupe_key)

            validated.append(
                {
                    "source_message_id": message_id,
                    "source_conversation_id": source_message.conversation_id,
                    "source_created_at": source_message.created_at,
                    "memory_type": memory_type,
                    "subject": subject.strip(),
                    # Automatic extraction stores evidence verbatim. The model's
                    # suggested summary is retained only for manual review.
                    "content": evidence.strip(),
                    "model_content": model_content.strip(),
                    "memory_key": memory_key.strip(),
                    "provenance": "explicit",
                    "confidence": float(confidence),
                    "importance": importance,
                    "evidence": evidence.strip(),
                }
            )

        return validated, skipped

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

        try:
            candidates, skipped = await self.extract_candidates(
                list(source_messages.values())
            )
        except Exception as error:
            for message_id in source_messages:
                self.queue.fail(message_id, str(error))
            return ExtractionReport(jobs_failed=len(source_messages))

        created = 0
        conflicts_queued = 0
        for candidate in candidates:
            try:
                existing = self.memory_store.get_memory_by_key(candidate["memory_key"])
                if existing is not None and not (
                    candidate["memory_type"] == "episodic"
                    and existing.memory_type == "episodic"
                ):
                    same_source = (
                        existing.source_message_id == candidate["source_message_id"]
                        and existing.source_conversation_id == candidate["source_conversation_id"]
                        and existing.source_created_at == candidate["source_created_at"]
                        and existing.evidence == candidate["evidence"]
                    )
                    if same_source:
                        skipped += 1
                    elif (
                        self.conflict_store is not None
                        and self.conflict_store.create_conflict_candidate(candidate, existing)
                    ):
                        conflicts_queued += 1
                    else:
                        skipped += 1
                    continue

                self.memory_store.create_memory(
                    content=candidate["content"],
                    memory_type=candidate["memory_type"],
                    subject=candidate["subject"],
                    memory_key=candidate["memory_key"],
                    provenance="explicit",
                    confidence=candidate["confidence"],
                    importance=candidate["importance"],
                    source_conversation_id=candidate["source_conversation_id"],
                    source_message_id=candidate["source_message_id"],
                    source_created_at=candidate["source_created_at"],
                    evidence=candidate["evidence"],
                )
                created += 1
            except (ValueError, TypeError):
                # A concurrent insert may win after the preflight lookup.
                existing = self.memory_store.get_memory_by_key(candidate["memory_key"])
                if (
                    existing is not None
                    and not (
                        candidate["memory_type"] == "episodic"
                        and existing.memory_type == "episodic"
                    )
                    and self.conflict_store is not None
                ):
                    if self.conflict_store.create_conflict_candidate(candidate, existing):
                        conflicts_queued += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1

        for message_id in source_messages:
            self.queue.complete(message_id)

        return ExtractionReport(
            jobs_completed=len(jobs),
            memories_created=created,
            candidates_skipped=skipped,
            conflicts_queued=conflicts_queued,
        )
