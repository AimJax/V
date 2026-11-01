"""Hybrid semantic and keyword memory retrieval."""

from __future__ import annotations

import math
from datetime import datetime

from v.memory.embedding_provider import LMStudioEmbeddingProvider
from v.memory.embedding_store import EmbeddingStore
from v.memory.models import Memory
from v.memory.retrieval import (
    meaningful_terms,
    resolve_temporal_memories,
    source_timestamp_key,
)
from v.memory.store import MemoryStore
from v.providers.errors import ProviderError


def cosine_similarity(
    left: tuple[float, ...] | list[float],
    right: tuple[float, ...] | list[float],
) -> float:
    if not left or len(left) != len(right):
        raise ValueError("Embedding dimensions must match and be non-empty.")

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))

    if not left_norm or not right_norm:
        raise ValueError("Embedding vectors must have non-zero magnitude.")

    return dot / (left_norm * right_norm)


def memory_document(memory: Memory) -> str:
    temporal = (
        f" Source date: {memory.source_created_at}."
        if memory.source_created_at
        else ""
    )
    return (
        f"{memory.memory_type}. {memory.subject}.{temporal} "
        f"{memory.content}"
    )


class HybridMemoryRetriever:
    """Retrieve relevant memories using local Nomic embeddings and FTS5."""

    def __init__(
        self,
        memory_store: MemoryStore,
        embedding_store: EmbeddingStore,
        embedding_provider: LMStudioEmbeddingProvider,
        *,
        model: str = "text-embedding-nomic-embed-text-v1.5",
        semantic_threshold: float = 0.60,
        limit: int = 5,
        batch_size: int = 16,
    ) -> None:
        if not model.strip():
            raise ValueError("Embedding model identifier is required.")

        if (
            not math.isfinite(semantic_threshold)
            or not 0 <= semantic_threshold <= 1
        ):
            raise ValueError("Semantic threshold must be between 0 and 1.")

        if limit < 1 or batch_size < 1:
            raise ValueError("Retrieval limit and batch size must be positive.")

        self.memory_store = memory_store
        self.embedding_store = embedding_store
        self.embedding_provider = embedding_provider
        self.model = model
        self.semantic_threshold = semantic_threshold
        self.limit = limit
        self.batch_size = batch_size
        self.last_fallback_reason: str | None = None

    async def _index_missing(self, memories: list[Memory]) -> None:
        valid = self.embedding_store.get_valid(self.model)

        pending = [
            memory
            for memory in memories
            if memory.id not in valid
        ]

        for start in range(0, len(pending), self.batch_size):
            batch = pending[start:start + self.batch_size]

            documents = [
                memory_document(memory)
                for memory in batch
            ]

            vectors = await self.embedding_provider.embed_documents(
                documents
            )

            if len(vectors) != len(batch):
                raise ValueError("Embedding provider returned the wrong count.")

            for memory, vector in zip(batch, vectors):
                self.embedding_store.put(
                    memory.id,
                    self.model,
                    vector,
                )


    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[Memory]:
        """Retrieve relevant memories, falling back to FTS5 if needed."""
        selected_limit = self.limit if limit is None else limit

        if selected_limit < 1:
            raise ValueError("Retrieval limit must be positive.")

        if not query.strip():
            return []

        memories = self.memory_store.list_memories(limit=10000)

        if not memories:
            return []

        query_terms = meaningful_terms(query)
        raw_lexical_results = (
            self.memory_store.search_memories_any(
                " ".join(query_terms),
                limit=max(selected_limit * 4, selected_limit),
            )
            if query_terms
            else []
        )
        lexical_ids = {memory.id for memory in raw_lexical_results}
        lexical_results = resolve_temporal_memories(
            raw_lexical_results,
            memories,
            query,
            limit=selected_limit,
        )

        self.last_fallback_reason = None

        try:
            await self._index_missing(memories)

            query_vectors = await self.embedding_provider.embed_queries(
                [query]
            )

            if len(query_vectors) != 1:
                raise ValueError("Embedding provider returned an invalid query count.")

            stored_vectors = self.embedding_store.get_valid(self.model)
            query_vector = query_vectors[0]

            ranked: list[tuple[float, int, tuple[int, datetime], int, str, Memory]] = []

            for memory in memories:
                vector = stored_vectors.get(memory.id)

                if vector is None:
                    continue

                similarity = cosine_similarity(query_vector, vector)
                lexical_match = memory.id in lexical_ids

                # Semantic match is primary. Exact keyword evidence provides
                # a modest recall allowance, not an unrestricted bypass.
                eligible = (
                    similarity >= self.semantic_threshold
                    or (
                        lexical_match
                        and similarity >= self.semantic_threshold - 0.15
                    )
                )

                if not eligible:
                    continue

                adjusted_score = similarity + (
                    0.025 if lexical_match else 0.0
                )

                ranked.append((
                    adjusted_score,
                    memory.importance,
                    source_timestamp_key(memory.source_created_at),
                    memory.source_message_id or 0,
                    memory.id,
                    memory,
                ))

            # Relevance remains primary. Chronology only breaks ranking ties;
            # recency never makes an otherwise ineligible memory relevant.
            ranked.sort(
                key=lambda item: (item[0], item[1], item[2], item[3], item[4]),
                reverse=True,
            )

            return resolve_temporal_memories(
                [item[5] for item in ranked],
                memories,
                query,
                limit=selected_limit,
            )

        except ProviderError as error:
            self.last_fallback_reason = str(error)

            # Preserve exact keyword recall if the embedding service
            # becomes unavailable. Do not pretend this is semantic search.
            return lexical_results

    async def rebuild_index(self) -> int:
        """Index all missing or stale memory documents."""
        memories = self.memory_store.list_memories(limit=10000)
        before = self.embedding_store.count(self.model)

        await self._index_missing(memories)

        after = self.embedding_store.count(self.model)
        return max(0, after - before)