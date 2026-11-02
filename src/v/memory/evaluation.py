"""Isolated, local-only benchmark for V's memory retrieval quality."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics

from dataclasses import dataclass
from pathlib import Path
from contextlib import closing
from tempfile import TemporaryDirectory
from typing import Protocol

from v.core.config import project_root
from v.memory.embedding_store import EmbeddingStore
from v.memory.models import Memory
from v.memory.hybrid_retrieval import (
    memory_document,
    rank_memory_candidates,
)
from v.memory.retrieval import (
    meaningful_terms,
    build_memory_context,
    resolve_temporal_memories,
)
from v.memory.store import MemoryStore
from v.providers.base import ChatMessage, ChatProvider
from v.providers.errors import ProviderAPIError


DEFAULT_THRESHOLDS = (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
DEFAULT_LIMIT = 5


class LocalEmbeddingProvider(Protocol):
    """The local embedding operations required by this benchmark."""

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass(frozen=True, slots=True)
class BenchmarkRecord:
    record_id: str
    memory_type: str
    subject: str
    content: str
    memory_key: str
    source_created_at: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkQuery:
    query: str
    relevant_record_ids: tuple[str, ...] = ()


# This is a fictional profile and project corpus. It never imports, reads,
# or writes the user's real memory database.
BENCHMARK_RECORDS = (
    BenchmarkRecord(
        "response_style", "preference", "Communication",
        "Prefers direct, concise answers that retain technical detail and include "
        "a concrete example when it materially improves understanding.",
        "benchmark.response_style",
    ),
    BenchmarkRecord(
        "coding_workflow", "preference", "Programming",
        "For programming help, prefers one actionable change at a time, exact "
        "commands, and a verification step after each change.",
        "benchmark.coding_workflow",
    ),
    BenchmarkRecord(
        "local_privacy", "preference", "Privacy",
        "Personal data, saved memories, and AI inference must remain on the local "
        "machine; cloud AI fallback and hidden telemetry are prohibited.",
        "benchmark.local_privacy",
    ),
    BenchmarkRecord(
        "v_project", "project", "V",
        "V is a persistent local-first AI companion for Windows with chat, voice, "
        "long-term memory, and a native desktop application.",
        "benchmark.v_project",
    ),
    BenchmarkRecord(
        "memory_review", "project", "Memory safety",
        "Historical memory imports must create review proposals. Existing saved "
        "memories must never be silently overwritten or deleted.",
        "benchmark.memory_review",
    ),
    BenchmarkRecord(
        "game_preferences", "preference", "Games",
        "Prefers turn-based tactical role-playing games with party customization, "
        "meaningful companion relationships, and optional romance systems.",
        "benchmark.game_preferences",
    ),
    BenchmarkRecord(
        "game_avoid", "preference", "Games",
        "Dislikes repetitive grinding, long unskippable cutscenes, and opaque "
        "character progression systems.",
        "benchmark.game_avoid",
    ),
    BenchmarkRecord(
        "field_project", "project", "Research",
        "Developing a marine field-station logger that records salinity, water "
        "temperature, dissolved oxygen, and GPS observations.",
        "benchmark.field_project",
    ),
    BenchmarkRecord(
        "music_genres", "preference", "Music",
        "Music interests include jazz fusion, funk, ambient electronic, and "
        "instrumental post-rock.",
        "benchmark.music_genres",
    ),
    BenchmarkRecord(
        "audio_workflow", "project", "Audio production",
        "Music production uses Ableton Live, Serum, and Kontakt for arrangement, "
        "synthesis, and sampled instruments.",
        "benchmark.audio_workflow",
    ),
    BenchmarkRecord(
        "art_workflow", "project", "Digital art",
        "The 3D-to-illustration workflow uses Blender for rendering and Krita for "
        "manual paint-over and final line-art adjustments.",
        "benchmark.art_workflow",
    ),
    BenchmarkRecord(
        "timezone", "fact", "Locale",
        "The fictional profile uses the America/Chicago timezone, with Central "
        "Time daylight-saving transitions.",
        "benchmark.timezone",
    ),
    BenchmarkRecord(
        "hardware_gpu", "fact", "Workstation",
        "The workstation graphics card is an AMD Radeon RX 7800 XT with 16 GB "
        "of video memory.",
        "benchmark.hardware_gpu",
    ),
    BenchmarkRecord(
        "work_2024", "episodic", "Employment",
        "Worked as an aquarium technician maintaining freshwater and marine "
        "exhibits during 2024.",
        "benchmark.work_role",
        "2024-06-15T09:00:00+00:00",
    ),
    BenchmarkRecord(
        "work_2026", "episodic", "Employment",
        "Currently works as a marine research coordinator at a coastal laboratory "
        "during 2026.",
        "benchmark.work_role",
        "2026-08-20T09:00:00+00:00",
    ),
    BenchmarkRecord(
        "voice_stack", "project", "Voice",
        "The local voice pipeline uses Whisper for speech recognition and Kokoro "
        "for text-to-speech; neither service sends audio to a cloud provider.",
        "benchmark.voice_stack",
    ),
    BenchmarkRecord(
        "offline_policy", "project", "Network policy",
        "Offline mode blocks external web access while allowing explicitly "
        "configured loopback inference endpoints to continue operating.",
        "benchmark.offline_policy",
    ),
)


BENCHMARK_QUERIES = (
    BenchmarkQuery(
        "How should technical answers be written?",
        ("response_style",),
    ),
    BenchmarkQuery(
        "Walk me through fixing a programming problem.",
        ("coding_workflow",),
    ),
    BenchmarkQuery(
        "Where should private conversations and model processing happen?",
        ("local_privacy",),
    ),
    BenchmarkQuery(
        "What Windows assistant is being developed and what can it do?",
        ("v_project",),
    ),
    BenchmarkQuery(
        "How should old chat history become saved memories?",
        ("memory_review",),
    ),
    BenchmarkQuery(
        "Which role-playing games fit a preference for party tactics and companions?",
        ("game_preferences",),
    ),
    BenchmarkQuery(
        "What gameplay design elements are disliked?",
        ("game_avoid",),
    ),
    BenchmarkQuery(
        "Which measurements does the marine research application collect?",
        ("field_project",),
    ),
    BenchmarkQuery(
        "What styles of music are of interest?",
        ("music_genres",),
    ),
    BenchmarkQuery(
        "Which applications are used for making music?",
        ("audio_workflow",),
    ),
    BenchmarkQuery(
        "How are 3D renders turned into finished illustrations?",
        ("art_workflow",),
    ),
    BenchmarkQuery(
        "Which timezone should local dates use?",
        ("timezone",),
    ),
    BenchmarkQuery(
        "What graphics card is installed in the workstation?",
        ("hardware_gpu",),
    ),
    BenchmarkQuery(
        "What was the aquarium-related job in 2024?",
        ("work_2024",),
    ),
    BenchmarkQuery(
        "What is the current role at the coastal laboratory?",
        ("work_2026",),
    ),
    BenchmarkQuery(
        "Which local engines handle speech input and spoken replies?",
        ("voice_stack",),
    ),
    BenchmarkQuery(
        "What network traffic remains possible when offline mode is enabled?",
        ("offline_policy",),
    ),
    BenchmarkQuery("What is the weather forecast for Reykjavik tomorrow?"),
    BenchmarkQuery("How do I make sourdough bread from scratch?"),
    BenchmarkQuery("Who won the latest international cricket championship?"),
)


def query_metrics(
    returned_record_ids: list[str],
    relevant_record_ids: tuple[str, ...],
) -> dict[str, float | int | bool]:
    """Calculate per-query metrics; empty relevance sets are rejection cases."""
    relevant = set(relevant_record_ids)
    returned = list(dict.fromkeys(returned_record_ids))

    if not relevant:
        return {
            "returned_count": len(returned),
            "false_positive": bool(returned),
            "precision": 0.0,
            "recall": 0.0,
            "reciprocal_rank": 0.0,
        }

    hits = [
        index
        for index, record_id in enumerate(returned, start=1)
        if record_id in relevant
    ]
    return {
        "returned_count": len(returned),
        "false_positive": False,
        "precision": len(hits) / len(returned) if returned else 0.0,
        "recall": len(hits) / len(relevant),
        "reciprocal_rank": 1.0 / hits[0] if hits else 0.0,
    }


def _aggregate(
    per_query: list[dict[str, float | int | bool]],
    *,
    positive_count: int,
    negative_count: int,
) -> dict[str, float | int | None]:
    positives = per_query[:positive_count]
    negatives = per_query[positive_count:]

    precision = statistics.fmean(float(item["precision"]) for item in positives)
    recall = statistics.fmean(float(item["recall"]) for item in positives)
    reciprocal_rank = statistics.fmean(
        float(item["reciprocal_rank"]) for item in positives
    )
    false_positive_rate = (
        sum(bool(item["false_positive"]) for item in negatives) / negative_count
        if negative_count
        else None
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    # A transparent ranking heuristic, not an automatic configuration change.
    # Positive-only sets cannot measure no-answer rejection, so use F1 alone.
    selection_score = (
        f1
        if false_positive_rate is None
        else f1 * (1.0 - false_positive_rate)
    )

    return {
        "precision": precision,
        "recall": recall,
        "mrr": reciprocal_rank,
        "false_positive_rate": false_positive_rate,
        "f1": f1,
        "selection_score": selection_score,
        "positive_queries": positive_count,
        "negative_queries": negative_count,
    }


def _build_corpus(store: MemoryStore) -> dict[str, str]:
    ids: dict[str, str] = {}
    for record in BENCHMARK_RECORDS:
        memory = store.create_memory(
            content=record.content,
            memory_type=record.memory_type,
            subject=record.subject,
            memory_key=record.memory_key,
            provenance="explicit",
            confidence=1.0,
            importance=3,
            source_created_at=record.source_created_at,
        )
        ids[record.record_id] = memory.id
    return ids


async def evaluate_memory_retrieval(
    embedding_provider: LocalEmbeddingProvider,
    *,
    model: str,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Sweep semantic thresholds against an isolated fictional benchmark corpus.

    Only a temporary SQLite database under V's ignored tmp directory is
    created. The user's configured memory database is never opened or changed.
    """
    if not model.strip():
        raise ValueError("Embedding model identifier is required.")
    if not thresholds:
        raise ValueError("At least one semantic threshold is required.")
    if limit < 1:
        raise ValueError("Retrieval limit must be positive.")
    if any(not 0 <= threshold <= 1 for threshold in thresholds):
        raise ValueError("All semantic thresholds must be between 0 and 1.")
    if len(set(thresholds)) != len(thresholds):
        raise ValueError("Semantic thresholds must be unique.")

    temporary_root = project_root() / "tmp" / "memory-evaluation"
    temporary_root.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="benchmark-", dir=temporary_root) as directory:
        database_path = Path(directory) / "benchmark.sqlite3"
        memory_store = MemoryStore(database_path)
        embedding_store = EmbeddingStore(database_path)
        record_ids = _build_corpus(memory_store)
        memories = memory_store.list_memories(limit=10000)

        documents = [memory_document(memory) for memory in memories]
        document_vectors = await embedding_provider.embed_documents(documents)
        if len(document_vectors) != len(memories):
            raise ValueError("Embedding provider returned the wrong document count.")

        for memory, vector in zip(memories, document_vectors):
            embedding_store.put(memory.id, model, vector)

        stored_vectors = embedding_store.get_valid(model)
        if len(stored_vectors) != len(memories):
            raise ValueError("The benchmark did not index every synthetic memory.")

        query_texts = [case.query for case in BENCHMARK_QUERIES]
        query_vectors = await embedding_provider.embed_queries(query_texts)
        if len(query_vectors) != len(BENCHMARK_QUERIES):
            raise ValueError("Embedding provider returned the wrong query count.")

        id_to_record = {memory_id: key for key, memory_id in record_ids.items()}
        positive_count = sum(
            bool(case.relevant_record_ids) for case in BENCHMARK_QUERIES
        )
        negative_count = len(BENCHMARK_QUERIES) - positive_count
        threshold_results = []

        for threshold in thresholds:
            per_query = []
            for case, query_vector in zip(BENCHMARK_QUERIES, query_vectors):
                terms = meaningful_terms(case.query)
                lexical = (
                    memory_store.search_memories_any(
                        " ".join(terms),
                        limit=max(limit * 4, limit),
                    )
                    if terms
                    else []
                )
                ranked = rank_memory_candidates(
                    memories,
                    query_vector,
                    stored_vectors,
                    {memory.id for memory in lexical},
                    semantic_threshold=threshold,
                )
                resolved = resolve_temporal_memories(
                    ranked,
                    memories,
                    case.query,
                    limit=limit,
                )
                returned_ids = [
                    id_to_record[memory.id]
                    for memory in resolved
                    if memory.id in id_to_record
                ]
                per_query.append(
                    query_metrics(returned_ids, case.relevant_record_ids)
                )

            threshold_results.append({
                "threshold": threshold,
                **_aggregate(
                    per_query,
                    positive_count=positive_count,
                    negative_count=negative_count,
                ),
            })

        # Measure the keyword-only fallback on the same corpus and labels.
        fts_metrics = []
        for case in BENCHMARK_QUERIES:
            terms = meaningful_terms(case.query)
            lexical = (
                memory_store.search_memories_any(
                    " ".join(terms),
                    limit=max(limit * 4, limit),
                )
                if terms
                else []
            )
            resolved = resolve_temporal_memories(
                lexical,
                memories,
                case.query,
                limit=limit,
            )
            returned_ids = [
                id_to_record[memory.id]
                for memory in resolved
                if memory.id in id_to_record
            ]
            fts_metrics.append(query_metrics(returned_ids, case.relevant_record_ids))

        fts_baseline = _aggregate(
            fts_metrics,
            positive_count=positive_count,
            negative_count=negative_count,
        )
        best = max(
            threshold_results,
            key=lambda item: (
                item["selection_score"],
                -item["false_positive_rate"],
                item["mrr"],
                item["threshold"],
            ),
        )

        return {
            "model": model,
            "corpus_size": len(BENCHMARK_RECORDS),
            "query_count": len(BENCHMARK_QUERIES),
            "positive_queries": positive_count,
            "negative_queries": negative_count,
            "limit": limit,
            "fts_baseline": fts_baseline,
            "thresholds": threshold_results,
            "best_scoring_threshold": best["threshold"],
            "selection_note": (
                "Heuristic ranking only: F1 multiplied by the negative-query "
                "rejection rate. This does not change V's configuration."
            ),
        }


PERSONAL_CASES_VERSION = 1
DEFAULT_PERSONAL_CASES_PATH = Path("data/memory/evaluation_cases.json")
PERSONAL_CASES_TEMPLATE = {
    "version": PERSONAL_CASES_VERSION,
    "instructions": [
        "Keep this file private. It is stored under V's ignored data directory.",
        "Write realistic questions you expect V to answer from saved memories.",
        "For relevant_memory_ids, paste full IDs from /memory search or Memory Manager.",
        "List every memory needed to answer a multi-memory question.",
        "For questions that should retrieve nothing, use an empty relevant_memory_ids array.",
        "For historical questions, label the historical snapshot IDs that answer the question.",
        "For present-state questions, label the latest relevant snapshot, not superseded history.",
        "No-answer cases are optional; add them only when you want to measure false positives.",
    ],
    "cases": [],
    "examples": [
        {
            "query": "What preferences have I stated about programming help?",
            "relevant_memory_ids": ["PASTE_FULL_MEMORY_ID"],
        },
        {
            "query": "How has my work situation changed over time?",
            "relevant_memory_ids": ["OLDER_MEMORY_ID", "LATEST_MEMORY_ID"],
        },
        {
            "query": "What did I say about owning a submarine?",
            "relevant_memory_ids": [],
        },
    ],
}


AUTO_PERSONAL_EVALUATION_MAX_MEMORIES = 40
AUTO_PERSONAL_EVALUATION_BATCH_SIZE = 6


def _select_evaluation_memories(
    memories: list[Memory],
    *,
    limit: int,
) -> list[Memory]:
    """Select a diverse, high-value sample without changing saved memories."""
    ranked = sorted(
        memories,
        key=lambda memory: (
            -memory.importance,
            -memory.confidence,
            memory.subject.casefold(),
            memory.id,
        ),
    )
    selected: list[Memory] = []
    seen_subjects: set[str] = set()
    remaining = list(ranked)

    while remaining and len(selected) < limit:
        index = next(
            (
                position
                for position, memory in enumerate(remaining)
                if memory.subject.casefold().strip() not in seen_subjects
            ),
            0,
        )
        memory = remaining.pop(index)
        selected.append(memory)
        seen_subjects.add(memory.subject.casefold().strip())

    return selected


def _parse_generated_cases(content: str) -> list[dict]:
    """Parse JSON generated by the local model, accepting common wrappers."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("The local chat model did not return valid JSON.")
        try:
            payload = json.loads(text[start:end + 1])
        except json.JSONDecodeError as error:
            raise ValueError(
                "The local chat model returned malformed evaluation JSON."
            ) from error

    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("The local chat model response must be a JSON object.")
    for key in ("cases", "questions", "queries", "items"):
        if isinstance(payload.get(key), list):
            return payload[key]
    raise ValueError("The local chat model response must contain a cases array.")


def _clean_generated_question(content: str) -> str | None:
    """Extract a question line from plain text without mistaking prose for one."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    question_start = re.compile(
        r"^(?:what|which|who|whom|whose|when|where|why|how|"
        r"do|does|did|is|are|was|were|have|has|had|can|could|would|"
        r"should|will|tell me|describe)\b",
        re.IGNORECASE,
    )
    for line in lines:
        cleaned = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s*)", "", line)
        cleaned = re.sub(r"^(?:question|query)\s*:\s*", "", cleaned, flags=re.I)
        cleaned = cleaned.strip().strip("`").strip('"').strip("'").strip()
        if not question_start.match(cleaned):
            continue
        question = cleaned.split("?", 1)[0].strip() + "?"
        if 8 <= len(question) <= 500:
            return question
    return None




def _fallback_evaluation_question(memory: Memory) -> str:
    """Create a conservative, source-linked question if the model misbehaves."""
    subject = memory.subject.strip() or "this topic"
    prompts = {
        "profile": f"What personal detail have I shared about {subject}?",
        "preference": f"What preferences have I shared about {subject}?",
        "episodic": f"What did I tell you about {subject} at that time?",
        "project": f"What do you remember about my {subject} project?",
        "relationship": f"What have I told you about {subject}?",
        "fact": f"What fact have I shared about {subject}?",
        "inferred_pattern": f"What pattern have you noticed about {subject}?",
    }
    return prompts.get(
        memory.memory_type,
        f"What do you remember about {subject}?",
    )




async def generate_personal_evaluation_cases(
    memories: list[Memory],
    chat_provider: ChatProvider,
    *,
    model: str,
    max_memories: int = AUTO_PERSONAL_EVALUATION_MAX_MEMORIES,
    batch_size: int = AUTO_PERSONAL_EVALUATION_BATCH_SIZE,
) -> tuple[list[BenchmarkQuery], dict]:
    """Generate source-anchored retrieval questions using V's configured local LLM.

    LM Studio JSON mode is preferred. If the model does not return valid JSON
    (or does not support JSON mode), V retries only the affected records using
    one plain-text question per request. Since each retry contains one memory,
    its source ID is unambiguous. A deterministic question is used only when
    the model's plain-text response is unusable.
    """
    if not model.strip():
        raise ValueError("A local chat model must be configured for personal evaluation.")
    if max_memories < 1 or batch_size < 1:
        raise ValueError("Evaluation memory and batch limits must be positive.")
    if not memories:
        raise ValueError("There are no saved memories to evaluate.")

    selected = _select_evaluation_memories(memories, limit=max_memories)
    cases_by_index: dict[int, BenchmarkQuery] = {}
    generation_methods: dict[int, str] = {}
    fallback_indexes: set[int] = set()
    deterministic_fallback_count = 0
    json_mode_prompt = (
        "You create retrieval evaluation questions for a private local AI assistant. "
        "For EACH supplied memory, create exactly one concise, natural question that "
        "requires the information in that specific memory to answer. Paraphrase the "
        "memory; do not copy its sentence. Do not ask a question answerable from "
        "general knowledge alone. Do not combine different memories. Never invent "
        "facts or request details absent from the memory. For an episodic memory with "
        "a source date, phrase the question as historical and anchor it to that date; "
        "do not imply that an old snapshot is current. If a record is too vague to "
        "support a useful question, omit it. Return JSON with a 'cases' array. Each "
        "item must contain the exact integer 'index' from the input and one string "
        "'query'. Include no other fields."
    )
    plain_text_system_prompt = (
        "Create exactly ONE natural question that a user could ask this assistant "
        "and that can only be answered from the supplied saved memory. Paraphrase "
        "the memory without revealing its answer. Do not invent details. If a source "
        "date is supplied, phrase the question historically and include that date. "
        "Output only the question as one plain-text line. No JSON, labels, numbering, "
        "Markdown, explanation, or extra text."
    )
    json_response_format = {"type": "json_object"}

    for start in range(0, len(selected), batch_size):
        batch = selected[start:start + batch_size]
        rows = [
            {
                "index": index,
                "memory_type": memory.memory_type,
                "subject": memory.subject,
                "source_date": memory.source_created_at,
                "content": memory.content[:1600],
            }
            for index, memory in enumerate(batch)
        ]
        try:
            response = await chat_provider.chat(
                [
                    ChatMessage(role="system", content=json_mode_prompt),
                    ChatMessage(
                        role="user",
                        content=json.dumps({"memories": rows}, ensure_ascii=False),
                    ),
                ],
                model=model,
                temperature=0.1,
                max_tokens=max(256, len(batch) * 96),
                response_format=json_response_format,
            )
            generated = _parse_generated_cases(response.content)
        except ValueError:
            generated = []
        except ProviderAPIError as error:
            if error.status_code not in {400, 422}:
                raise
            generated = []

        for item in generated:
            if not isinstance(item, dict):
                continue
            index = item.get(
                "index",
                item.get("memory_index", item.get("record_index")),
            )
            query = item.get(
                "query",
                item.get("question", item.get("text")),
            )
            if (
                type(index) is not int
                or not 0 <= index < len(batch)
                or (start + index) in cases_by_index
                or not isinstance(query, str)
                or not 8 <= len(query.strip()) <= 500
            ):
                continue
            memory = batch[index]
            stable_index = start + index
            cases_by_index[stable_index] = BenchmarkQuery(
                query.strip(),
                (memory.id,),
            )
            generation_methods[stable_index] = "json"

        for local_index, memory in enumerate(batch):
            stable_index = start + local_index
            if stable_index in cases_by_index:
                continue
            fallback_indexes.add(stable_index)
            plain_response = await chat_provider.chat(
                [
                    ChatMessage(role="system", content=plain_text_system_prompt),
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "memory_type": memory.memory_type,
                                "subject": memory.subject,
                                "source_date": memory.source_created_at,
                                "content": memory.content[:1600],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
                model=model,
                temperature=0.1,
                max_tokens=96,
            )
            query = _clean_generated_question(plain_response.content)
            if query is None:
                query = _fallback_evaluation_question(memory)
                deterministic_fallback_count += 1
                generation_methods[stable_index] = "deterministic"
            else:
                generation_methods[stable_index] = "plain_text"
            cases_by_index[stable_index] = BenchmarkQuery(
                query,
                (memory.id,),
            )

    cases = [cases_by_index[index] for index in sorted(cases_by_index)]
    if not cases:
        raise ValueError(
            "V could not create any usable evaluation questions from saved memories."
        )

    summary = {
        "method": "local source-anchored generation",
        "model": model,
        "saved_memories": len(memories),
        "sampled_memories": len(selected),
        "generated_queries": len(cases),
        "plain_text_retries": len(fallback_indexes),
        "deterministic_fallbacks": deterministic_fallback_count,
        "skipped_memories": len(selected) - len(cases),
        "question_previews": [
            {
                "memory_id": selected[index].id,
                "subject": selected[index].subject,
                "query": cases_by_index[index].query,
                "generation_method": generation_methods.get(index, "unknown"),
            }
            for index in sorted(cases_by_index)
        ],
        "cases_saved_to_disk": False,
    }
    return cases, summary


def _validate_thresholds(
    thresholds: tuple[float, ...],
    limit: int,
) -> None:
    if not thresholds:
        raise ValueError("At least one semantic threshold is required.")
    if any(
        not math.isfinite(threshold) or not 0 <= threshold <= 1
        for threshold in thresholds
    ):
        raise ValueError("All semantic thresholds must be finite values from 0 to 1.")
    if len(set(thresholds)) != len(thresholds):
        raise ValueError("Semantic thresholds must be unique.")
    if limit < 1:
        raise ValueError("Retrieval limit must be positive.")


def resolve_personal_cases_path(
    path: str | Path | None = None,
) -> Path:
    """Resolve an evaluation-label file without allowing paths outside V_HOME."""
    root = project_root().resolve()
    configured = DEFAULT_PERSONAL_CASES_PATH if path is None else Path(path)
    resolved = (
        configured.expanduser()
        if configured.is_absolute()
        else root / configured.expanduser()
    ).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Personal evaluation files must remain inside V_HOME.")
    return resolved


def create_personal_cases_template(
    destination: str | Path | None = None,
) -> Path:
    """Create a private starter file without overwriting an existing file."""
    path = resolve_personal_cases_path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        PERSONAL_CASES_TEMPLATE,
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as file:
            file.write(serialized)
    except FileExistsError:
        raise FileExistsError(
            f"Evaluation case file already exists; it was not overwritten: {path}"
        ) from None
    return path


def load_personal_cases(
    path: str | Path,
    available_memory_ids: set[str],
) -> list[BenchmarkQuery]:
    """Load and validate human-labeled queries and existing memory IDs."""
    cases_path = resolve_personal_cases_path(path)
    try:
        data = json.loads(cases_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Could not read personal evaluation file: {cases_path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Personal evaluation file is not valid JSON at line {error.lineno}."
        ) from error

    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data.get("version") != PERSONAL_CASES_VERSION
    ):
        raise ValueError(
            f"Personal evaluation file must be an object with version "
            f"{PERSONAL_CASES_VERSION}."
        )

    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Add at least one test case to the 'cases' array.")

    result: list[BenchmarkQuery] = []
    unknown_ids: set[str] = set()
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Evaluation case {index} must be a JSON object.")

        query = item.get("query")
        ids = item.get("relevant_memory_ids")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"Evaluation case {index} needs a non-empty query.")
        if not isinstance(ids, list) or any(
            not isinstance(memory_id, str) or not memory_id.strip()
            for memory_id in ids
        ):
            raise ValueError(
                f"Evaluation case {index} needs a relevant_memory_ids array "
                "containing full memory ID strings."
            )
        normalized_ids = tuple(memory_id.strip() for memory_id in ids)
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError(f"Evaluation case {index} contains duplicate memory IDs.")
        unknown_ids.update(set(normalized_ids) - available_memory_ids)
        result.append(BenchmarkQuery(query.strip(), normalized_ids))

    if unknown_ids:
        preview = ", ".join(sorted(unknown_ids)[:5])
        suffix = "…" if len(unknown_ids) > 5 else ""
        raise ValueError(
            "Some labeled memory IDs do not exist in the current memory database: "
            f"{preview}{suffix}. Refresh your labels after deleting or changing memories."
        )

    if not any(case.relevant_record_ids for case in result):
        raise ValueError("At least one case must label one or more relevant memories.")
    return result


def _load_cached_embeddings_read_only(
    database_path: Path,
    model: str,
    memories: list[Memory],
) -> dict[str, tuple[float, ...]]:
    """Read valid cached vectors without creating tables or writing to SQLite."""
    uri = f"{database_path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'memory_embeddings'
            """
        ).fetchone()
        if table is None:
            return {}

        rows = connection.execute(
            """
            SELECT e.memory_id, e.dimensions, e.vector, e.content_hash,
                   m.content, m.memory_type, m.subject
            FROM memory_embeddings AS e
            JOIN memories AS m ON m.id = e.memory_id
            WHERE e.model = ?
            """,
            (model,),
        ).fetchall()

    memories_by_id = {memory.id: memory for memory in memories}
    valid: dict[str, tuple[float, ...]] = {}
    for row in rows:
        memory = memories_by_id.get(row["memory_id"])
        if memory is None:
            continue
        digest = EmbeddingStore._content_hash(
            row["memory_type"],
            row["subject"],
            row["content"],
        )
        if digest != row["content_hash"]:
            continue
        valid[row["memory_id"]] = EmbeddingStore._decode_vector(
            row["vector"],
            row["dimensions"],
        )
    return valid


async def evaluate_personal_memory_retrieval(
    memory_store: MemoryStore,
    embedding_provider: LocalEmbeddingProvider,
    cases: list[BenchmarkQuery],
    *,
    model: str,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    limit: int = DEFAULT_LIMIT,
    batch_size: int = 32,
    max_context_characters: int = 2400,
) -> dict:
    """Evaluate the real memory corpus without writing to its DB or vector cache.

    Existing compatible embeddings are read through a SQLite read-only
    connection. Missing/stale vectors are created in RAM in bounded batches.
    The configured memory database and embedding cache are never modified.
    """
    if not model.strip():
        raise ValueError("Embedding model identifier is required.")
    _validate_thresholds(thresholds, limit)
    if not getattr(memory_store, "read_only", False):
        raise ValueError(
            "Personal evaluation requires MemoryStore(read_only=True)."
        )
    if not cases:
        raise ValueError("At least one personal evaluation case is required.")
    if not any(case.relevant_record_ids for case in cases):
        raise ValueError("At least one personal case must label relevant memories.")
    if batch_size < 1:
        raise ValueError("Embedding batch size must be positive.")
    if max_context_characters < 1:
        raise ValueError("Memory context character limit must be positive.")

    memories = memory_store.list_memories(limit=10000)
    if not memories:
        raise ValueError("There are no saved memories to evaluate.")

    available_ids = {memory.id for memory in memories}
    for index, case in enumerate(cases, start=1):
        if not isinstance(case.query, str) or not case.query.strip():
            raise ValueError(f"Evaluation case {index} has an empty query.")
        if set(case.relevant_record_ids) - available_ids:
            raise ValueError(
                f"Evaluation case {index} refers to memory IDs that no longer exist."
            )

    try:
        stored_vectors = _load_cached_embeddings_read_only(
            memory_store.database_path,
            model,
            memories,
        )
    except sqlite3.Error as error:
        raise ValueError(
            f"Could not read the existing embedding cache in read-only mode: {error}"
        ) from error
    pending = [
        memory for memory in memories
        if memory.id not in stored_vectors
    ]
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        vectors = await embedding_provider.embed_documents(
            [memory_document(memory) for memory in batch]
        )
        if len(vectors) != len(batch):
            raise ValueError("Embedding provider returned the wrong document count.")
        for memory, vector in zip(batch, vectors):
            stored_vectors[memory.id] = tuple(float(value) for value in vector)

    if len(stored_vectors) != len(memories):
        raise ValueError("Could not obtain a valid vector for every saved memory.")

    query_vectors = await embedding_provider.embed_queries(
        [case.query for case in cases]
    )
    if len(query_vectors) != len(cases):
        raise ValueError("Embedding provider returned the wrong query count.")

    query_details_by_threshold: dict[float, list[dict]] = {}
    threshold_results: list[dict] = []

    for threshold in thresholds:
        per_case: list[dict] = []
        for index, (case, query_vector) in enumerate(
            zip(cases, query_vectors),
            start=1,
        ):
            terms = meaningful_terms(case.query)
            lexical = (
                memory_store.search_memories_any(
                    " ".join(terms),
                    limit=max(limit * 4, limit),
                )
                if terms
                else []
            )
            ranked = rank_memory_candidates(
                memories,
                query_vector,
                stored_vectors,
                {memory.id for memory in lexical},
                semantic_threshold=threshold,
            )
            resolved = resolve_temporal_memories(
                ranked,
                memories,
                case.query,
                limit=limit,
            )
            returned_ids = [memory.id for memory in resolved]
            metrics = query_metrics(returned_ids, case.relevant_record_ids)
            context = build_memory_context(
                resolved,
                max_characters=max_context_characters,
            )
            per_case.append({
                "case": index,
                "query": case.query,
                "returned_memory_ids": returned_ids,
                "relevant_memory_ids": list(case.relevant_record_ids),
                "missing_relevant_memory_ids": sorted(
                    set(case.relevant_record_ids) - set(returned_ids)
                ),
                **metrics,
                "context_characters": len(context or ""),
            })

        positives = [
            item for item, case in zip(per_case, cases)
            if case.relevant_record_ids
        ]
        negatives = [
            item for item, case in zip(per_case, cases)
            if not case.relevant_record_ids
        ]
        ordered_metrics = positives + negatives
        aggregate = _aggregate(
            ordered_metrics,
            positive_count=len(positives),
            negative_count=len(negatives),
        )
        aggregate["mean_context_characters"] = statistics.fmean(
            item["context_characters"] for item in per_case
        )
        aggregate["mean_returned_memories"] = statistics.fmean(
            item["returned_count"] for item in per_case
        )
        threshold_results.append({
            "threshold": threshold,
            **aggregate,
        })
        query_details_by_threshold[threshold] = per_case

    fts_details = []
    for index, case in enumerate(cases, start=1):
        terms = meaningful_terms(case.query)
        lexical = (
            memory_store.search_memories_any(
                " ".join(terms),
                limit=max(limit * 4, limit),
            )
            if terms
            else []
        )
        resolved = resolve_temporal_memories(
            lexical,
            memories,
            case.query,
            limit=limit,
        )
        returned_ids = [memory.id for memory in resolved]
        metrics = query_metrics(returned_ids, case.relevant_record_ids)
        context = build_memory_context(
            resolved,
            max_characters=max_context_characters,
        )
        fts_details.append({
            "case": index,
            "query": case.query,
            "returned_memory_ids": returned_ids,
            "relevant_memory_ids": list(case.relevant_record_ids),
            "missing_relevant_memory_ids": sorted(
                set(case.relevant_record_ids) - set(returned_ids)
            ),
            **metrics,
            "context_characters": len(context or ""),
        })

    positives = [
        item for item, case in zip(fts_details, cases)
        if case.relevant_record_ids
    ]
    negatives = [
        item for item, case in zip(fts_details, cases)
        if not case.relevant_record_ids
    ]
    fts_baseline = _aggregate(
        positives + negatives,
        positive_count=len(positives),
        negative_count=len(negatives),
    )
    fts_baseline["mean_context_characters"] = statistics.fmean(
        item["context_characters"] for item in fts_details
    )
    fts_baseline["mean_returned_memories"] = statistics.fmean(
        item["returned_count"] for item in fts_details
    )

    best = max(
        threshold_results,
        key=lambda item: (
            item["selection_score"],
            -(item["false_positive_rate"] or 0.0),
            item["mrr"],
            item["threshold"],
        ),
    )
    return {
        "model": model,
        "memory_count": len(memories),
        "query_count": len(cases),
        "positive_queries": len(positives),
        "negative_queries": len(negatives),
        "limit": limit,
        "max_context_characters": max_context_characters,
        "cached_embeddings_reused": len(memories) - len(pending),
        "embeddings_generated_in_memory": len(pending),
        "fts_baseline": fts_baseline,
        "thresholds": threshold_results,
        "query_details": query_details_by_threshold,
        "fts_query_details": fts_details,
        "best_scoring_threshold": best["threshold"],
        "selection_note": (
            "Heuristic ranking only: F1 multiplied by the negative-query "
            "rejection rate. Inspect per-query misses and false positives "
            "before changing the production threshold."
            if negatives
            else
            "Positive-only evaluation: the score is F1. No-answer rejection "
            "was not measured in this run. Generated questions are "
            "source-anchored calibration cases, not a human-verified test set."
        ),
        "database_modified": False,
    }
