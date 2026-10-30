import unittest

from pathlib import Path

from support import temporary_directory

from v.memory.embedding_store import EmbeddingStore
from v.memory.store import MemoryStore


class EmbeddingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        self.database = Path(self.temp_dir.name) / "memory.sqlite3"

        self.memory_store = MemoryStore(self.database)
        self.embedding_store = EmbeddingStore(self.database)

        self.memory = self.memory_store.create_memory(
            content="I enjoy software development.",
            memory_type="preference",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_vector_round_trip(self):
        vector = [0.1, 0.2, -0.3, 0.4]

        self.embedding_store.put(
            self.memory.id,
            "test-embedding-model",
            vector,
        )

        result = self.embedding_store.get_valid("test-embedding-model")

        self.assertEqual(len(result[self.memory.id]), 4)

        for actual, expected in zip(result[self.memory.id], vector):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_content_change_invalidates_embedding(self):
        self.embedding_store.put(
            self.memory.id,
            "test-model",
            [0.1, 0.2, 0.3],
        )

        self.memory_store.update_memory(
            self.memory.id,
            content="I enjoy ambient music.",
        )

        self.assertEqual(
            self.embedding_store.get_valid("test-model"),
            {},
        )

        self.assertEqual(
            self.embedding_store.missing_memory_ids("test-model"),
            [self.memory.id],
        )

    def test_wrong_model_is_not_returned(self):
        self.embedding_store.put(
            self.memory.id,
            "model-a",
            [0.1, 0.2],
        )

        self.assertEqual(
            self.embedding_store.get_valid("model-b"),
            {},
        )

    def test_vector_validation(self):
        for vector in ([], [float("nan")], [float("inf")], [True]):
            with self.subTest(vector=vector):
                with self.assertRaises(ValueError):
                    self.embedding_store.put(
                        self.memory.id,
                        "test-model",
                        vector,
                    )

    def test_missing_memory_is_rejected(self):
        with self.assertRaises(KeyError):
            self.embedding_store.put(
                "does-not-exist",
                "test-model",
                [0.1],
            )

    def test_delete_memory_removes_embedding(self):
        self.embedding_store.put(
            self.memory.id,
            "test-model",
            [0.1, 0.2],
        )

        self.assertTrue(
            self.memory_store.delete_memory(self.memory.id)
        )

        self.assertEqual(self.embedding_store.count(), 0)

    def test_embedding_count(self):
        self.embedding_store.put(
            self.memory.id,
            "test-model",
            [0.1, 0.2],
        )

        self.assertEqual(self.embedding_store.count(), 1)
        self.assertEqual(
            self.embedding_store.count("test-model"),
            1,
        )


if __name__ == "__main__":
    unittest.main()