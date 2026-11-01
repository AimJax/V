"""Cancellable idle-time memory extraction worker."""

from __future__ import annotations

import asyncio

from v.memory.extractor import MemoryExtractor


class MemoryWorker:
    """Run extraction only after a period without new user messages."""

    def __init__(
        self,
        extractor: MemoryExtractor,
        *,
        idle_delay_seconds: float = 20.0,
        max_jobs_per_cycle: int = 3,
    ) -> None:
        if idle_delay_seconds < 0:
            raise ValueError("Idle delay cannot be negative.")

        if max_jobs_per_cycle < 1:
            raise ValueError("Maximum jobs per cycle must be positive.")

        self.extractor = extractor
        self.idle_delay_seconds = idle_delay_seconds
        self.max_jobs_per_cycle = max_jobs_per_cycle

        self._task: asyncio.Task | None = None
        self.last_error: str | None = None
        self.last_report = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def schedule(self) -> None:
        """Restart the idle countdown."""
        await self.cancel()

        self.last_error = None
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            await asyncio.sleep(self.idle_delay_seconds)

            for _ in range(self.max_jobs_per_cycle):
                report = await self.extractor.process_pending(limit=5)
                self.last_report = report

                if report.jobs_failed:
                    break

                if report.jobs_completed < 5:
                    break

        except asyncio.CancelledError:
            raise

        except Exception as error:
            self.last_error = str(error)[:1000]

    async def cancel(self) -> None:
        """Stop active extraction without removing pending jobs."""
        task = self._task

        if task is None:
            return

        self._task = None

        if not task.done():
            task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        await self.cancel()