import tempfile
import unittest

from pathlib import Path

from v.memory.queue import ExtractionQueue


class ExtractionQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=r"G:\V\tmp")
        self.database_path = Path(self.temp_dir.name) / "queue.sqlite3"
        self.queue = ExtractionQueue(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_enqueue_and_list(self):
        self.assertTrue(self.queue.enqueue("conversation-1", 10))
        jobs = self.queue.list_pending()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source_message_id"], 10)

    def test_enqueue_is_idempotent(self):
        self.assertTrue(self.queue.enqueue("conversation-1", 10))
        self.assertFalse(self.queue.enqueue("conversation-1", 10))
        self.assertEqual(self.queue.count(), 1)

    def test_completed_job_is_not_pending(self):
        self.queue.enqueue("conversation-1", 10)
        self.queue.complete(10)

        self.assertEqual(self.queue.count("completed"), 1)
        self.assertEqual(self.queue.list_pending(), [])

    def test_failed_job_can_be_retried(self):
        self.queue.enqueue("conversation-1", 10)
        self.queue.fail(10, "Temporary failure", max_attempts=1)

        self.assertEqual(self.queue.count("failed"), 1)
        self.assertEqual(self.queue.retry_failed(), 1)
        self.assertEqual(self.queue.count("pending"), 1)

    def test_failure_retries_until_limit(self):
        self.queue.enqueue("conversation-1", 10)

        self.queue.fail(10, "First failure", max_attempts=3)
        self.assertEqual(self.queue.count("pending"), 1)

        self.queue.fail(10, "Second failure", max_attempts=3)
        self.assertEqual(self.queue.count("pending"), 1)

        self.queue.fail(10, "Third failure", max_attempts=3)
        self.assertEqual(self.queue.count("failed"), 1)

    def test_invalid_message_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.queue.enqueue("conversation-1", 0)


if __name__ == "__main__":
    unittest.main()