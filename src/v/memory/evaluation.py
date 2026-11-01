"""Isolated, local-only benchmark for V's memory retrieval quality."""

from __future__ import annotations

import statistics

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from v.core.config import project_root
from v.memory.embedding_store import EmbeddingStore
from v.memory.hybrid_retrieval import (
    memory_document,
    rank_memory_candidates,
)
from v.memory.retrieval import (
    meaningful_terms,
    resolve_temporal_memories,
)
from v.memory.store import MemoryStore


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
) -> dict[str, float | int]:
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
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    # A transparent ranking heuristic, not an automatic configuration change.
    selection_score = f1 * (1.0 - false_positive_rate)

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
