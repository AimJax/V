import json
import unittest

from pathlib import Path
from unittest.mock import patch

from support import temporary_directory
from v.memory.embedding_store import EmbeddingStore
from v.memory.evaluation import (
    BENCHMARK_QUERIES,
    BENCHMARK_RECORDS,
    BenchmarkQuery,
    create_personal_cases_template,
    evaluate_memory_retrieval,
    evaluate_personal_memory_retrieval,
    load_personal_cases,
    query_metrics,
    resolve_personal_cases_path,
)
from v.memory.store import MemoryStore


class EqualVectorProvider:
    def __init__(self):
        self.document_batches = []
        self.query_batches = []

    async def embed_documents(self, texts):
        self.document_batches.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]

    async def embed_queries(self, texts):
        self.query_batches.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]


class MemoryEvaluationTests(unittest.IsolatedAsyncioTestCase):
    def test_query_metrics_handle_positive_and_no_answer_cases(self):
        positive = query_metrics(
            ["irrelevant", "expected", "duplicate", "expected"],
            ("expected",),
        )
        self.assertAlmostEqual(positive["precision"], 1 / 3)
        self.assertEqual(positive["recall"], 1.0)
        self.assertEqual(positive["reciprocal_rank"], 0.5)

        rejected = query_metrics([], ())
        self.assertFalse(rejected["false_positive"])

        false_positive = query_metrics(["irrelevant"], ())
        self.assertTrue(false_positive["false_positive"])

    async def test_evaluation_uses_one_batch_and_only_temporary_data(self):
        provider = EqualVectorProvider()

        with temporary_directory() as temporary:
            root = Path(temporary)
            with patch("v.memory.evaluation.project_root", return_value=root):
                report = await evaluate_memory_retrieval(
                    provider,
                    model="test-local-embedding",
                    thresholds=(0.50, 0.60),
                )

            temporary_root = root / "tmp" / "memory-evaluation"
            self.assertTrue(temporary_root.is_dir())
            self.assertEqual(list(temporary_root.iterdir()), [])

        self.assertEqual(len(provider.document_batches), 1)
        self.assertEqual(
            len(provider.document_batches[0]),
            len(BENCHMARK_RECORDS),
        )
        self.assertEqual(len(provider.query_batches), 1)
        self.assertEqual(
            len(provider.query_batches[0]),
            len(BENCHMARK_QUERIES),
        )

        self.assertEqual(report["corpus_size"], len(BENCHMARK_RECORDS))
        self.assertEqual(report["query_count"], len(BENCHMARK_QUERIES))
        self.assertEqual(report["positive_queries"], 17)
        self.assertEqual(report["negative_queries"], 3)
        self.assertEqual(
            [item["threshold"] for item in report["thresholds"]],
            [0.50, 0.60],
        )
        self.assertIn(report["best_scoring_threshold"], (0.50, 0.60))
        self.assertIn("fts_baseline", report)

    async def test_invalid_thresholds_are_rejected(self):
        provider = EqualVectorProvider()
        with self.assertRaises(ValueError):
            await evaluate_memory_retrieval(
                provider,
                model="test-local-embedding",
                thresholds=(0.60, 1.20),
            )

    def test_personal_template_is_local_and_never_overwritten(self):
        with temporary_directory() as temporary:
            root = Path(temporary)
            with patch("v.memory.evaluation.project_root", return_value=root):
                path = create_personal_cases_template()
                template = json.loads(path.read_text(encoding="utf-8"))

                self.assertEqual(template["version"], 1)
                self.assertEqual(template["cases"], [])
                self.assertTrue(template["examples"])
                with self.assertRaises(FileExistsError):
                    create_personal_cases_template()

                with self.assertRaisesRegex(ValueError, "inside V_HOME"):
                    resolve_personal_cases_path("../outside.json")

    def test_personal_case_loader_rejects_stale_memory_ids(self):
        with temporary_directory() as temporary:
            root = Path(temporary)
            path = root / "cases.json"
            path.write_text(
                json.dumps({
                    "version": 1,
                    "cases": [{
                        "query": "What did I say about programming?",
                        "relevant_memory_ids": ["deleted-memory"],
                    }],
                }),
                encoding="utf-8",
            )
            with patch("v.memory.evaluation.project_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "do not exist"):
                    load_personal_cases(path, {"current-memory"})

    async def test_personal_evaluation_reuses_cache_and_does_not_write(self):
        class PersonalProvider:
            def __init__(self):
                self.document_batches = []
                self.query_batches = []

            async def embed_documents(self, texts):
                self.document_batches.append(list(texts))
                return [
                    [0.0, 1.0] if "gardening" in text.casefold() else [1.0, 0.0]
                    for text in texts
                ]

            async def embed_queries(self, texts):
                self.query_batches.append(list(texts))
                return [
                    [1.0, 0.0] if "style" in text.casefold() else [0.0, -1.0]
                    for text in texts
                ]

        with temporary_directory() as temporary:
            database = Path(temporary) / "memory.sqlite3"
            memories = MemoryStore(database)
            vectors = EmbeddingStore(database)
            preference = memories.create_memory(
                content="I prefer technical detail in explanations.",
                memory_type="preference",
                subject="Communication",
            )
            memories.create_memory(
                content="The user enjoys gardening and growing herbs.",
                memory_type="preference",
                subject="Hobbies",
            )
            vectors.put(preference.id, "test-local", [1.0, 0.0])

            before = vectors.count("test-local")
            original_vectors = vectors.get_valid("test-local")
            before_memory_count = memories.count_memories()
            read_only_memories = MemoryStore(database, read_only=True)
            provider = PersonalProvider()
            with patch("v.memory.evaluation.project_root", return_value=Path(temporary)):
                cases = [
                    BenchmarkQuery(
                        "What response style do I prefer?",
                        (preference.id,),
                    ),
                    BenchmarkQuery(
                        "What have I said about submarines?",
                    ),
                ]
                report = await evaluate_personal_memory_retrieval(
                    read_only_memories,
                    provider,
                    cases,
                    model="test-local",
                    thresholds=(0.60, 0.70),
                )

            self.assertEqual(report["memory_count"], 2)
            self.assertEqual(report["cached_embeddings_reused"], 1)
            self.assertEqual(report["embeddings_generated_in_memory"], 1)
            self.assertEqual(len(provider.document_batches), 1)
            self.assertEqual(len(provider.document_batches[0]), 1)
            self.assertIn("gardening", provider.document_batches[0][0])
            self.assertEqual(len(provider.query_batches), 1)
            self.assertEqual(vectors.count("test-local"), before)
            self.assertEqual(vectors.get_valid("test-local"), original_vectors)
            self.assertEqual(read_only_memories.count_memories(), before_memory_count)
            self.assertEqual(set(vectors.get_valid("test-local")), {preference.id})
            self.assertFalse(report["database_modified"])
            self.assertEqual(
                report["thresholds"][0]["precision"],
                1.0,
            )
            self.assertEqual(
                report["thresholds"][0]["false_positive_rate"],
                0.0,
            )

    async def test_personal_evaluation_rejects_unknown_labels(self):
        with temporary_directory() as temporary:
            database = Path(temporary) / "memory.sqlite3"
            memories = MemoryStore(database)
            memories.create_memory(content="A saved memory.")
            read_only_memories = MemoryStore(database, read_only=True)
            provider = EqualVectorProvider()

            with self.assertRaisesRegex(ValueError, "no longer exist"):
                await evaluate_personal_memory_retrieval(
                    read_only_memories,
                    provider,
                    [
                        BenchmarkQuery(
                            "What was saved?",
                            ("missing-id",),
                        ),
                        BenchmarkQuery("A query with no relevant memory."),
                    ],
                    model="test-local",
                    thresholds=(0.60,),
                )


if __name__ == "__main__":
    unittest.main()
