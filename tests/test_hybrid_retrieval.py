import unittest

from pathlib import Path

from support import temporary_directory

from v.memory.embedding_store import EmbeddingStore
from v.memory.hybrid_retrieval import (
    HybridMemoryRetriever,
    cosine_similarity,
)
from v.memory.store import MemoryStore
from v.providers.errors import ProviderConnectionError


class FakeEmbeddingProvider:
    def __init__(self):
        self.document_calls = 0
        self.query_calls = 0
        self.fail = False

    async def embed_documents(self, texts):
        self.document_calls += 1

        if self.fail:
            raise ProviderConnectionError("Test offline.")

        return [[1.0, 0.0] for _ in texts]

    async def embed_queries(self, texts):
        self.query_calls += 1

        if self.fail:
            raise ProviderConnectionError("Test offline.")

        results = []

        for text in texts:
            lowered = text.casefold()

            if any(term in lowered for term in ("work", "job", "employment")):
                results.append([1.0, 0.0])
            elif "programming" in lowered or "coding" in lowered:
                results.append([0.8, 0.6])
            elif "weather" in lowered or "movie" in lowered:
                results.append([0.5, 0.8660254])
            elif "software" in lowered or "technical" in lowered:
                results.append([0.95, 0.31225])
            else:
                results.append([0.5, 0.8660254])

        return results


class HybridRetrievalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        database = Path(self.temp_dir.name) / "memory.sqlite3"

        self.memories = MemoryStore(database)
        self.embeddings = EmbeddingStore(database)
        self.provider = FakeEmbeddingProvider()

        self.preference = self.memories.create_memory(
            content=(
                "I prefer concise responses with technical detail "
                "when we're discussing software development."
            ),
            memory_type="preference",
            subject="User",
            provenance="explicit",
            confidence=1.0,
            importance=4,
        )

        self.retriever = HybridMemoryRetriever(
            self.memories,
            self.embeddings,
            self.provider,
            semantic_threshold=0.60,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_semantic_retrieval_handles_different_wording(self):
        results = await self.retriever.retrieve(
            "How should you help me when programming?"
        )

        self.assertEqual(
            [memory.id for memory in results],
            [self.preference.id],
        )

    async def test_unrelated_query_is_rejected(self):
        results = await self.retriever.retrieve(
            "What is the weather forecast?"
        )

        self.assertEqual(results, [])

    async def test_technical_explanation_query_is_relevant(self):
        results = await self.retriever.retrieve(
            "How do I prefer technical explanations?"
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, self.preference.id)

    async def test_missing_vectors_are_indexed(self):
        self.assertEqual(self.embeddings.count(), 0)

        await self.retriever.retrieve("programming help")

        self.assertEqual(self.embeddings.count(), 1)
        self.assertEqual(self.provider.document_calls, 1)

    async def test_existing_vectors_are_reused(self):
        await self.retriever.retrieve("programming help")
        await self.retriever.retrieve("coding help")

        self.assertEqual(self.provider.document_calls, 1)
        self.assertEqual(self.provider.query_calls, 2)

    async def test_unavailable_embedding_service_uses_fts(self):
        self.provider.fail = True

        results = await self.retriever.retrieve(
            "software development"
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, self.preference.id)
        self.assertIsNotNone(self.retriever.last_fallback_reason)

    async def test_subject_change_invalidates_embedding(self):
        await self.retriever.retrieve("programming help")

        self.memories.update_memory(
            self.preference.id,
            subject="Programming",
        )

        self.assertEqual(
            self.embeddings.get_valid(
                "text-embedding-nomic-embed-text-v1.5"
            ),
            {},
        )


    async def test_present_query_uses_latest_recorded_timeline_snapshot(self):
        older = self.memories.create_memory(
            content="The user had work at a coastal industrial site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2024-03-12T09:15:00+00:00",
        )
        newer = self.memories.create_memory(
            content="The user has work in a different construction role.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2026-10-30T09:15:00+00:00",
        )

        results = await self.retriever.retrieve("Where do I work now?")

        self.assertEqual([item.id for item in results], [newer.id])
        self.assertNotIn(older.id, [item.id for item in results])

    async def test_historical_query_preserves_the_full_timeline(self):
        older = self.memories.create_memory(
            content="The user had work at a coastal industrial site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2024-03-12T09:15:00+00:00",
        )
        newer = self.memories.create_memory(
            content="The user has work in a different construction role.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2026-10-30T09:15:00+00:00",
        )

        results = await self.retriever.retrieve("Where did I work in 2024?")

        self.assertEqual(
            [item.id for item in results],
            [older.id, newer.id],
        )

    async def test_offline_keyword_fallback_uses_latest_snapshot(self):
        self.memories.create_memory(
            content="The user had work at a coastal industrial site.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2024-03-12T09:15:00+00:00",
        )
        newer = self.memories.create_memory(
            content="The user has work in a different construction role.",
            memory_type="episodic",
            memory_key="user.work_context",
            source_created_at="2026-10-30T09:15:00+00:00",
        )
        self.provider.fail = True

        results = await self.retriever.retrieve("Where do I work now?")

        self.assertEqual([item.id for item in results], [newer.id])
        self.assertIsNotNone(self.retriever.last_fallback_reason)

    async def test_cosine_similarity(self):
        result = cosine_similarity(
            [1.0, 0.0],
            [0.8, 0.6],
        )

        self.assertAlmostEqual(result, 0.8, places=6)


if __name__ == "__main__":
    unittest.main()