"""Durable queue for automatic memory extraction."""

from __future__ import annotations

import sqlite3

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ExtractionQueue:
    """Persist extraction jobs so they survive application restarts."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_extraction_jobs (
                    source_message_id INTEGER PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'completed', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_jobs_status
                ON memory_extraction_jobs(status, created_at)
                """
            )
            connection.commit()

    def enqueue(self, conversation_id: str, message_id: int) -> bool:
        """Queue a user message once. Returns False if already queued."""
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ValueError("A conversation ID is required.")

        if (
            isinstance(message_id, bool)
            or not isinstance(message_id, int)
            or message_id < 1
        ):
            raise ValueError("A positive message ID is required.")

        now = _now()

        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO memory_extraction_jobs (
                        source_message_id,
                        conversation_id,
                        status,
                        attempts,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, 'pending', 0, ?, ?)
                    """,
                    (message_id, conversation_id, now, now),
                )

        return cursor.rowcount > 0

    def list_pending(self, limit: int = 5) -> list[dict]:
        if limit < 1:
            raise ValueError("Queue limit must be positive.")

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT source_message_id, conversation_id, attempts
                FROM memory_extraction_jobs
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_failed(self, limit: int = 5) -> list[dict]:
        """Return recent failed jobs with their retry diagnostics."""
        if limit < 1:
            raise ValueError("Queue limit must be positive.")

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT source_message_id, conversation_id,
                       attempts, last_error, created_at, updated_at
                FROM memory_extraction_jobs
                WHERE status = 'failed'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def complete(self, message_id: int) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE memory_extraction_jobs
                    SET status = 'completed',
                        updated_at = ?,
                        last_error = NULL
                    WHERE source_message_id = ?
                    """,
                    (_now(), message_id),
                )

    def fail(
        self,
        message_id: int,
        error: str,
        *,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive.")

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE memory_extraction_jobs
                    SET attempts = attempts + 1,
                        status = CASE
                            WHEN attempts + 1 >= ? THEN 'failed'
                            ELSE 'pending'
                        END,
                        last_error = ?,
                        updated_at = ?
                    WHERE source_message_id = ?
                    """,
                    (
                        max_attempts,
                        str(error)[:1000],
                        _now(),
                        message_id,
                    ),
                )

    def retry_failed(self) -> int:
        """Reset failed jobs for an explicit retry."""
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE memory_extraction_jobs
                    SET status = 'pending',
                        attempts = 0,
                        last_error = NULL,
                        updated_at = ?
                    WHERE status = 'failed'
                    """,
                    (_now(),),
                )

        return cursor.rowcount

    def count(self, status: str | None = None) -> int:
        with closing(self._connect()) as connection:
            if status is None:
                row = connection.execute(
                    "SELECT COUNT(*) FROM memory_extraction_jobs"
                ).fetchone()
            else:
                if status not in {"pending", "completed", "failed"}:
                    raise ValueError("Invalid job status.")

                row = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM memory_extraction_jobs
                    WHERE status = ?
                    """,
                    (status,),
                ).fetchone()

        return int(row[0])