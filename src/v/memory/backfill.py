"""Durable historical memory reprocessing and human review."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows hosts use fcntl
    msvcrt = None

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt
    fcntl = None


from v.conversations.store import ConversationStore
from v.memory.extractor import MemoryExtractor
from v.memory.store import MemoryStore


_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MemoryBackfillStore:
    """Persist backfill checkpoints and review decisions in the memory DB."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.database_path.with_name(
            self.database_path.name + ".backfill.lock"
        )
        self._lock_handle = None
        self._local_run_lock: threading.Lock | None = None
        with _LOCAL_LOCKS_GUARD:
            self._process_lock = _LOCAL_LOCKS.setdefault(
                str(self._lock_path),
                threading.Lock(),
            )
        self._initialize()
        self.recover_interrupted_runs()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_backfill_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'running', 'paused', 'failed', 'completed')
                    ),
                    upper_message_id INTEGER NOT NULL DEFAULT 0,
                    cursor_message_id INTEGER NOT NULL DEFAULT 0,
                    total_messages INTEGER NOT NULL DEFAULT 0,
                    processed_messages INTEGER NOT NULL DEFAULT 0,
                    candidates_found INTEGER NOT NULL DEFAULT 0,
                    candidates_skipped INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_memory_backfill_runs_created
                    ON memory_backfill_runs(created_at DESC);

                CREATE TABLE IF NOT EXISTS memory_review_candidates (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    source_conversation_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (
                        status IN ('pending', 'approved', 'rejected', 'duplicate')
                    ),
                    review_note TEXT,
                    approved_memory_id TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES memory_backfill_runs(id)
                        ON DELETE RESTRICT,
                );

                CREATE INDEX IF NOT EXISTS idx_memory_review_status
                    ON memory_review_candidates(status, created_at);

                CREATE INDEX IF NOT EXISTS idx_memory_review_run
                    ON memory_review_candidates(run_id, source_message_id);
                """
            )
            connection.commit()

            candidate_schema = connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'table' AND name = 'memory_review_candidates'
                """
            ).fetchone()
            normalized_schema = (
                "".join(candidate_schema["sql"].split())
                if candidate_schema is not None
                else ""
            )
            if "UNIQUE(run_id,source_message_id,memory_key)" in normalized_schema:
                # Older review databases allowed only one proposal per key
                # within a source message. Rebuild without that constraint so
                # multiple episodic facts from one long message are retained.
                connection.execute("PRAGMA foreign_keys = OFF")
                try:
                    connection.executescript(
                        """
                        BEGIN;
                        CREATE TABLE memory_review_candidates_new (
                            id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL,
                            source_message_id INTEGER NOT NULL,
                            source_conversation_id TEXT NOT NULL,
                            memory_key TEXT NOT NULL,
                            payload_json TEXT NOT NULL,
                            status TEXT NOT NULL DEFAULT 'pending' CHECK (
                                status IN ('pending', 'approved', 'rejected', 'duplicate')
                            ),
                            review_note TEXT,
                            approved_memory_id TEXT,
                            created_at TEXT NOT NULL,
                            reviewed_at TEXT,
                            FOREIGN KEY (run_id) REFERENCES memory_backfill_runs(id)
                                ON DELETE RESTRICT
                        );
                        INSERT INTO memory_review_candidates_new
                        SELECT * FROM memory_review_candidates;
                        DROP TABLE memory_review_candidates;
                        ALTER TABLE memory_review_candidates_new
                            RENAME TO memory_review_candidates;
                        CREATE INDEX idx_memory_review_status
                            ON memory_review_candidates(status, created_at);
                        CREATE INDEX idx_memory_review_run
                            ON memory_review_candidates(run_id, source_message_id);
                        COMMIT;
                        """
                    )
                finally:
                    connection.execute("PRAGMA foreign_keys = ON")

    def acquire_run_lock(self) -> bool:
        """Acquire an exclusive cross-process lock for the historical scanner."""
        if self._lock_handle is not None:
            return True
        if not self._process_lock.acquire(blocking=False):
            return False

        handle = None
        try:
            handle = self._lock_path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)

            if os.name == "nt":
                if msvcrt is None:
                    raise RuntimeError("Windows file-lock support is unavailable.")
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            elif fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                raise RuntimeError("No supported file-lock implementation is available.")
        except (OSError, BlockingIOError):
            if handle is not None:
                handle.close()
            self._process_lock.release()
            return False
        except Exception:
            if handle is not None:
                handle.close()
            self._process_lock.release()
            raise

        self._lock_handle = handle
        self._local_run_lock = self._process_lock
        return True

    def release_run_lock(self) -> None:
        """Release the cross-process scan lock."""
        handle = self._lock_handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                if msvcrt is not None:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._lock_handle = None
            local_lock = self._local_run_lock
            self._local_run_lock = None
            if local_lock is not None:
                local_lock.release()

    def recover_interrupted_runs(self) -> int:
        """Pause abandoned runs only when no other process owns the scan lock."""
        if not self.acquire_run_lock():
            return 0
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        """
                        UPDATE memory_backfill_runs
                        SET status = 'paused',
                            last_error = 'Application closed before the scan finished.',
                            updated_at = ?
                        WHERE status IN ('queued', 'running')
                        """,
                        (_now(),),
                    )
            return cursor.rowcount
        finally:
            self.release_run_lock()

    def create_run(self, *, upper_message_id: int, total_messages: int) -> dict:
        if upper_message_id < 0 or total_messages < 0:
            raise ValueError("Backfill message bounds cannot be negative.")
        import uuid

        run_id = uuid.uuid4().hex
        now = _now()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO memory_backfill_runs (
                        id, status, upper_message_id, cursor_message_id,
                        total_messages, processed_messages, candidates_found,
                        candidates_skipped, created_at, updated_at
                    )
                    VALUES (?, 'queued', ?, 0, ?, 0, 0, 0, ?, ?)
                    """,
                    (run_id, upper_message_id, total_messages, now, now),
                )
        result = self.get_run(run_id)
        if result is None:
            raise RuntimeError("Backfill run could not be retrieved.")
        return result

    def latest_run(self) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_backfill_runs
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def get_run(self, run_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memory_backfill_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def set_run_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        if status not in {"running", "paused", "failed", "completed"}:
            raise ValueError("Unsupported backfill run status.")
        completed_at = _now() if status == "completed" else None
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE memory_backfill_runs
                    SET status = ?, last_error = ?, updated_at = ?,
                        completed_at = COALESCE(?, completed_at)
                    WHERE id = ?
                    """,
                    (status, error[:1000] if error else None, _now(), completed_at, run_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Backfill run not found: {run_id}")

    def save_batch(
        self,
        run_id: str,
        *,
        last_message_id: int,
        processed_messages: int,
        candidates: list[dict],
        candidates_skipped: int,
    ) -> dict:
        """Atomically save proposals and advance the scan checkpoint."""
        if processed_messages < 1 or candidates_skipped < 0:
            raise ValueError("Invalid backfill batch counts.")
        now = _now()
        inserted = 0
        with closing(self._connect()) as connection:
            with connection:
                run = connection.execute(
                    "SELECT status, cursor_message_id FROM memory_backfill_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if run is None:
                    raise KeyError(f"Backfill run not found: {run_id}")
                if run["status"] != "running":
                    raise RuntimeError("Backfill run is not active.")
                if last_message_id <= int(run["cursor_message_id"]):
                    raise ValueError("Backfill checkpoint must move forward.")

                for candidate in candidates:
                    source_id = int(candidate["source_message_id"])
                    memory_key = str(candidate["memory_key"])
                    evidence_fingerprint = hashlib.sha256(
                        str(candidate.get("evidence", "")).encode("utf-8")
                    ).hexdigest()
                    stable_id = hashlib.sha256(
                        f"{run_id}:{source_id}:{memory_key}:{evidence_fingerprint}".encode("utf-8")
                    ).hexdigest()[:32]
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO memory_review_candidates (
                            id, run_id, source_message_id, source_conversation_id,
                            memory_key, payload_json, status, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (
                            stable_id,
                            run_id,
                            source_id,
                            str(candidate["source_conversation_id"]),
                            memory_key,
                            json.dumps(candidate, ensure_ascii=False, allow_nan=False),
                            now,
                        ),
                    )
                    inserted += max(0, cursor.rowcount)

                connection.execute(
                    """
                    UPDATE memory_backfill_runs
                    SET cursor_message_id = ?,
                        processed_messages = processed_messages + ?,
                        candidates_found = candidates_found + ?,
                        candidates_skipped = candidates_skipped + ?,
                        last_error = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        last_message_id,
                        processed_messages,
                        inserted,
                        candidates_skipped,
                        now,
                        run_id,
                    ),
                )
        result = self.get_run(run_id)
        if result is None:
            raise RuntimeError("Backfill checkpoint could not be retrieved.")
        return result

    def get_candidate(self, candidate_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memory_review_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def list_candidates(
        self,
        *,
        status: str = "pending",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        if status not in {"pending", "approved", "rejected", "duplicate", "all"}:
            raise ValueError("Unsupported memory review status.")
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("Invalid memory review pagination.")
        where = "" if status == "all" else "WHERE status = ?"
        parameters: list[object] = [] if status == "all" else [status]
        parameters.extend([limit, offset])
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM memory_review_candidates
                {where}
                ORDER BY created_at ASC, source_message_id ASC
                LIMIT ? OFFSET ?
                """,
                parameters,
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            results.append(item)
        return results

    def mark_candidate(
        self,
        candidate_id: str,
        status: str,
        *,
        note: str | None = None,
        approved_memory_id: str | None = None,
    ) -> None:
        if status not in {"approved", "rejected", "duplicate"}:
            raise ValueError("Unsupported candidate decision.")
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE memory_review_candidates
                    SET status = ?, review_note = ?, approved_memory_id = ?,
                        reviewed_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (
                        status,
                        note[:1000] if note else None,
                        approved_memory_id,
                        _now(),
                        candidate_id,
                    ),
                )
                if cursor.rowcount != 1:
                    existing = connection.execute(
                        "SELECT status FROM memory_review_candidates WHERE id = ?",
                        (candidate_id,),
                    ).fetchone()
                    if existing is None:
                        raise KeyError(f"Memory candidate not found: {candidate_id}")
                    raise ValueError(
                        f"Candidate is already {existing['status']} and cannot be reviewed again."
                    )


class MemoryBackfillRunner:
    """Reprocess historical user messages into a durable approval queue."""

    def __init__(
        self,
        conversations: ConversationStore,
        extractor: MemoryExtractor,
        memory_store: MemoryStore,
        review_store: MemoryBackfillStore,
        *,
        batch_size: int = 5,
    ) -> None:
        if not 1 <= batch_size <= 20:
            raise ValueError("Backfill batch size must be between 1 and 20.")
        self.conversations = conversations
        self.extractor = extractor
        self.memory_store = memory_store
        self.review_store = review_store
        self.batch_size = batch_size
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> dict | None:
        return self.review_store.latest_run()

    async def run(
        self,
        *,
        new_run: bool = False,
        on_progress: Callable[[dict], None] | None = None,
    ) -> dict:
        if self._running:
            raise RuntimeError("A historical memory scan is already running.")
        if not self.review_store.acquire_run_lock():
            raise RuntimeError(
                "A historical memory scan is already active in another V process."
            )

        self._running = True
        run_id: str | None = None
        try:
            latest = self.review_store.latest_run()
            if new_run:
                upper = self.conversations.max_user_message_id()
                total = self.conversations.count_user_messages(through_id=upper)
                run = self.review_store.create_run(
                    upper_message_id=upper,
                    total_messages=total,
                )
            elif latest is None:
                upper = self.conversations.max_user_message_id()
                total = self.conversations.count_user_messages(through_id=upper)
                run = self.review_store.create_run(
                    upper_message_id=upper,
                    total_messages=total,
                )
            elif latest["status"] in {"queued", "paused", "failed"}:
                run = latest
            elif latest["status"] == "completed":
                raise RuntimeError(
                    "Historical backfill is already complete. Use --new-run to "
                    "reprocess the full history with the current extraction rules."
                )
            else:
                raise RuntimeError("The latest historical scan is already active.")

            run_id = run["id"]
            self.review_store.set_run_status(run_id, "running")
            if on_progress is not None:
                active = self.review_store.get_run(run_id)
                if active is not None:
                    on_progress(active)

            while True:
                current = self.review_store.get_run(run_id)
                if current is None:
                    raise RuntimeError("Backfill run disappeared.")
                page = self.conversations.list_user_messages(
                    after_id=int(current["cursor_message_id"]),
                    through_id=int(current["upper_message_id"]),
                    limit=self.batch_size,
                )
                if not page:
                    self.review_store.set_run_status(run_id, "completed")
                    break

                candidates, skipped = await self.extractor.extract_candidates(page)
                progress = self.review_store.save_batch(
                    run_id,
                    last_message_id=page[-1].id,
                    processed_messages=len(page),
                    candidates=candidates,
                    candidates_skipped=skipped,
                )
                if on_progress is not None:
                    on_progress(progress)

            result = self.review_store.get_run(run_id)
            if result is None:
                raise RuntimeError("Backfill completed but its run record is missing.")
            return result

        except asyncio.CancelledError:
            if run_id is not None:
                self.review_store.set_run_status(run_id, "paused")
            raise
        except Exception as error:
            if run_id is not None:
                self.review_store.set_run_status(run_id, "failed", error=str(error))
            raise
        finally:
            self._running = False
            self.review_store.release_run_lock()

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        changes: dict | None = None,
    ):
        return MemoryReviewService(
            self.memory_store,
            self.review_store,
        ).approve_candidate(candidate_id, changes=changes)

    def reject_candidate(self, candidate_id: str, *, reason: str = "") -> None:
        MemoryReviewService(
            self.memory_store,
            self.review_store,
        ).reject_candidate(candidate_id, reason=reason)


class MemoryReviewService:
    """Apply explicit approve/reject decisions without invoking a model."""

    def __init__(
        self,
        memory_store: MemoryStore,
        review_store: MemoryBackfillStore,
    ) -> None:
        self.memory_store = memory_store
        self.review_store = review_store

    def approve_candidate(self, candidate_id: str, *, changes: dict | None = None):
        candidate = self.review_store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"Memory candidate not found: {candidate_id}")
        if candidate["status"] != "pending":
            raise ValueError(f"Candidate is already {candidate['status']}.")

        payload = dict(candidate["payload"])
        changes = dict(changes or {})
        allowed = {
            "memory_type", "subject", "content", "memory_key",
            "confidence", "importance",
        }
        unexpected = set(changes) - allowed
        if unexpected:
            raise ValueError(f"Unsupported candidate edits: {sorted(unexpected)}")
        payload.update(changes)
        if (
            not isinstance(payload.get("memory_key"), str)
            or not payload["memory_key"].strip()
        ):
            raise ValueError("Approved backfill memories require a non-empty memory key.")

        try:
            memory = self.memory_store.create_memory(
                content=str(payload.get("content") or payload["evidence"]).strip(),
                memory_type=payload["memory_type"],
                subject=payload["subject"],
                memory_key=payload["memory_key"],
                provenance="explicit",
                confidence=float(payload["confidence"]),
                importance=int(payload["importance"]),
                source_conversation_id=payload["source_conversation_id"],
                source_message_id=int(payload["source_message_id"]),
                source_created_at=payload.get("source_created_at"),
                evidence=payload["evidence"],
            )
        except ValueError as error:
            if "already exists with key" not in str(error):
                raise
            existing = self.memory_store.get_memory_by_key(payload["memory_key"])
            if existing is not None:
                same_source = (
                    existing.source_message_id == int(payload["source_message_id"])
                    and existing.source_conversation_id == payload["source_conversation_id"]
                    and existing.source_created_at == payload.get("source_created_at")
                    and existing.evidence == payload["evidence"]
                )
                if same_source:
                    self.review_store.mark_candidate(
                        candidate_id,
                        "approved",
                        note="Already imported from this exact source.",
                        approved_memory_id=existing.id,
                    )
                    return existing
                self.review_store.mark_candidate(
                    candidate_id,
                    "duplicate",
                    note=f"Conflicts with existing memory {existing.id}: {error}",
                    approved_memory_id=existing.id,
                )
                raise ValueError(
                    f"Candidate conflicts with existing memory {existing.id}; "
                    "the existing record was not changed."
                ) from error
            raise

        self.review_store.mark_candidate(
            candidate_id,
            "approved",
            approved_memory_id=memory.id,
        )
        return memory

    def reject_candidate(self, candidate_id: str, *, reason: str = "") -> None:
        candidate = self.review_store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"Memory candidate not found: {candidate_id}")
        self.review_store.mark_candidate(
            candidate_id,
            "rejected",
            note=reason or "Rejected during manual review.",
        )
