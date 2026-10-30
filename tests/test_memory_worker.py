import asyncio
import unittest

from types import SimpleNamespace

from v.memory.worker import MemoryWorker


class FakeExtractor:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.block = False
        self.cancelled = False

    async def process_pending(self, limit=1):
        self.calls += 1
        self.started.set()

        if self.block:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        return SimpleNamespace(
            jobs_completed=1,
            jobs_failed=0,
            memories_created=0,
        )


class MemoryWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_after_idle_delay(self):
        extractor = FakeExtractor()
        worker = MemoryWorker(
            extractor,
            idle_delay_seconds=0.01,
            max_jobs_per_cycle=1,
        )

        await worker.schedule()
        await asyncio.sleep(0.05)

        self.assertEqual(extractor.calls, 1)
        self.assertFalse(worker.running)

        await worker.close()

    async def test_cancellation_prevents_pending_work(self):
        extractor = FakeExtractor()
        worker = MemoryWorker(
            extractor,
            idle_delay_seconds=0.05,
        )

        await worker.schedule()
        await worker.cancel()
        await asyncio.sleep(0.07)

        self.assertEqual(extractor.calls, 0)
        self.assertFalse(worker.running)

    async def test_new_schedule_restarts_idle_countdown(self):
        extractor = FakeExtractor()
        worker = MemoryWorker(
            extractor,
            idle_delay_seconds=0.05,
            max_jobs_per_cycle=1,
        )

        await worker.schedule()
        await asyncio.sleep(0.025)

        await worker.schedule()
        await asyncio.sleep(0.025)

        self.assertEqual(extractor.calls, 0)

        await asyncio.sleep(0.05)

        self.assertEqual(extractor.calls, 1)
        await worker.close()

    async def test_cancellation_interrupts_active_extraction(self):
        extractor = FakeExtractor()
        extractor.block = True

        worker = MemoryWorker(
            extractor,
            idle_delay_seconds=0,
        )

        await worker.schedule()
        await asyncio.wait_for(extractor.started.wait(), timeout=1)

        await worker.cancel()

        self.assertTrue(extractor.cancelled)
        self.assertFalse(worker.running)

    async def test_processes_multiple_pending_jobs_per_cycle(self):
        extractor = FakeExtractor()
        worker = MemoryWorker(
            extractor,
            idle_delay_seconds=0,
            max_jobs_per_cycle=3,
        )

        await worker.schedule()
        await asyncio.sleep(0.05)

        self.assertEqual(extractor.calls, 3)
        await worker.close()

    async def test_validates_worker_settings(self):
        extractor = FakeExtractor()

        with self.assertRaises(ValueError):
            MemoryWorker(extractor, idle_delay_seconds=-1)

        with self.assertRaises(ValueError):
            MemoryWorker(extractor, max_jobs_per_cycle=0)


if __name__ == "__main__":
    unittest.main()