import unittest

from pathlib import Path
from unittest.mock import patch

from support import temporary_directory
from v.memory.evaluation import (
    BENCHMARK_QUERIES,
    BENCHMARK_RECORDS,
    evaluate_memory_retrieval,
    query_metrics,
)


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


if __name__ == "__main__":
    unittest.main()
