"""Temporal continuity metadata and prospective commitments for V's memory store.

This module extends the existing memory SQLite database. It does not create a
second memory repository or rewrite source memory records.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MEMORY_STATES = {"current", "superseded", "corrected", "disputed", "expired"}
COMMITMENT_STATES = {"open", "completed", "cancelled"}
DERIVATION_STATES = {"pending", "accepted", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _timestamp(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an ISO-8601 string or None.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class ContinuityStore:
    """Add time-aware lifecycle and prospective records to a MemoryStore DB."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        database_path: Path | str,
        *,
        migrate_legacy_evidence: bool = True,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)
        with closing(self._connect()) as db:
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "memories" not in tables:
                raise RuntimeError("Continuity requires the existing memories table.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memory_temporal (
                    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                    state TEXT NOT NULL DEFAULT 'current'
                        CHECK (state IN ('current','superseded','corrected','disputed','expired')),
                    valid_from TEXT,
                    valid_until TEXT,
                    recorded_at TEXT NOT NULL,
                    superseded_by TEXT REFERENCES memories(id) ON DELETE SET NULL,
                    note TEXT NOT NULL DEFAULT '',
                    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_temporal_state
                    ON memory_temporal(state, valid_from, valid_until);

                CREATE TABLE IF NOT EXISTS memory_derivations (
                    derived_memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    source_memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK (state IN ('pending','accepted','rejected')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (derived_memory_id, source_memory_id),
                    CHECK (derived_memory_id != source_memory_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_derivations_source
                    ON memory_derivations(source_memory_id);
                DROP TRIGGER IF EXISTS continuity_source_changed;
                CREATE TRIGGER continuity_source_changed
                AFTER UPDATE OF content, subject, provenance, evidence, memory_key,
                                source_conversation_id, source_message_id,
                                source_created_at ON memories
                BEGIN
                    INSERT OR IGNORE INTO memory_temporal(
                        memory_id, state, recorded_at, note
                    )
                    SELECT derived_memory_id, 'disputed',
                           strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'),
                           'A supporting source changed; this derived record requires review.'
                    FROM memory_derivations
                    WHERE source_memory_id=OLD.id AND state='accepted';
                    UPDATE memory_temporal
                    SET state='disputed',
                        note='A supporting source changed; this derived record requires review.'
                    WHERE memory_id IN (
                        SELECT derived_memory_id FROM memory_derivations
                        WHERE source_memory_id=OLD.id AND state='accepted'
                    );
                    UPDATE memory_derivations SET state='rejected'
                    WHERE source_memory_id=OLD.id AND state='accepted';
                END;

                CREATE TABLE IF NOT EXISTS memory_commitments (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 240),
                    description TEXT NOT NULL DEFAULT '',
                    due_at TEXT,
                    recurrence TEXT,
                    state TEXT NOT NULL DEFAULT 'open'
                        CHECK (state IN ('open','completed','cancelled')),
                    source_memory_id TEXT REFERENCES memories(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_commitments_due
                    ON memory_commitments(state, due_at);
                DROP TRIGGER IF EXISTS continuity_memory_delete;
                CREATE TRIGGER continuity_memory_delete
                BEFORE DELETE ON memories
                BEGIN
                    INSERT OR IGNORE INTO memory_temporal(
                        memory_id, state, recorded_at, note
                    )
                    SELECT derived_memory_id, 'disputed',
                           strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'),
                           'A supporting source was deleted; this derived record requires review.'
                    FROM memory_derivations
                    WHERE source_memory_id=OLD.id AND state='accepted';
                    UPDATE memory_temporal
                    SET state='disputed',
                        note='A supporting source was deleted; this derived record requires review.'
                    WHERE memory_id IN (
                        SELECT derived_memory_id FROM memory_derivations
                        WHERE source_memory_id=OLD.id AND state='accepted'
                    );
                    UPDATE memory_derivations
                    SET state='rejected'
                    WHERE source_memory_id=OLD.id AND state='accepted';
                    UPDATE memory_commitments
                    SET source_memory_id=NULL
                    WHERE source_memory_id=OLD.id;
                END;
            """)
            existing_tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if migrate_legacy_evidence and "memory_evidence" in existing_tables:
                # Upgrade existing inferred patterns into the review-gated
                # derivation model without changing their source evidence.
                db.execute(
                    """
                    INSERT OR IGNORE INTO memory_derivations(
                        derived_memory_id, source_memory_id, state, created_at
                    )
                    SELECT e.pattern_memory_id, e.source_memory_id, 'pending', e.created_at
                    FROM memory_evidence AS e
                    JOIN memories AS derived ON derived.id=e.pattern_memory_id
                    WHERE derived.memory_type='inferred_pattern'
                      AND derived.provenance='inferred'
                    """
                )
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.database_path), timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def ensure_temporal_record(
        self, memory_id: str, *, valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> dict[str, Any]:
        start = _timestamp(valid_from, "valid_from")
        end = _timestamp(valid_until, "valid_until")
        if start and end and end < start:
            raise ValueError("valid_until cannot precede valid_from.")
        with closing(self._connect()) as db:
            exists = db.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone()
            if exists is None:
                raise KeyError(memory_id)
            db.execute("""
                INSERT INTO memory_temporal(memory_id, valid_from, valid_until, recorded_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    valid_from=COALESCE(excluded.valid_from, memory_temporal.valid_from),
                    valid_until=COALESCE(excluded.valid_until, memory_temporal.valid_until)
            """, (memory_id, start, end, _now()))
            db.commit()
            return dict(db.execute(
                "SELECT * FROM memory_temporal WHERE memory_id=?", (memory_id,)
            ).fetchone())

    def temporal_record(self, memory_id: str) -> dict[str, Any]:
        """Return temporal metadata, using an explicit current default if absent."""
        with closing(self._connect()) as db:
            if db.execute(
                "SELECT 1 FROM memories WHERE id=?", (memory_id,)
            ).fetchone() is None:
                raise KeyError(memory_id)
            row = db.execute(
                "SELECT * FROM memory_temporal WHERE memory_id=?", (memory_id,)
            ).fetchone()
            if row is not None:
                return dict(row)
            return {
                "memory_id": memory_id,
                "state": "current",
                "valid_from": None,
                "valid_until": None,
                "recorded_at": None,
                "superseded_by": None,
                "note": "",
            }

    def set_memory_state(
        self, memory_id: str, state: str, *, superseded_by: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        if not isinstance(state, str) or state not in MEMORY_STATES:
            raise ValueError(f"Unsupported memory state: {state}")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory_id must be a non-empty string.")
        if superseded_by is not None and (
            not isinstance(superseded_by, str) or not superseded_by
        ):
            raise ValueError("superseded_by must be a non-empty string or None.")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError("note must be a string of at most 2000 characters.")
        if state == "superseded" and not superseded_by:
            raise ValueError("A superseded memory must identify its replacement.")
        if state != "superseded" and superseded_by is not None:
            raise ValueError("Only a superseded memory may identify a replacement.")
        if superseded_by == memory_id:
            raise ValueError("A memory cannot supersede itself.")
        with closing(self._connect()) as db:
            if db.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone() is None:
                raise KeyError(memory_id)
            if superseded_by and db.execute(
                "SELECT 1 FROM memories WHERE id=?", (superseded_by,)
            ).fetchone() is None:
                raise KeyError(superseded_by)
            db.execute("""
                INSERT INTO memory_temporal(memory_id, state, recorded_at, superseded_by, note)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    state=excluded.state, superseded_by=excluded.superseded_by, note=excluded.note
            """, (memory_id, state, _now(), superseded_by, note.strip()))
            db.commit()
            return dict(db.execute(
                "SELECT * FROM memory_temporal WHERE memory_id=?", (memory_id,)
            ).fetchone())

    def update_temporal_record(
        self,
        memory_id: str,
        state: str,
        *,
        valid_from: str | None = None,
        valid_until: str | None = None,
        superseded_by: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Atomically update lifecycle and validity, including clearing dates."""
        if not isinstance(state, str) or state not in MEMORY_STATES:
            raise ValueError(f"Unsupported memory state: {state}")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory_id must be a non-empty string.")
        if superseded_by is not None and (
            not isinstance(superseded_by, str) or not superseded_by
        ):
            raise ValueError("superseded_by must be a non-empty string or None.")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError("note must be a string of at most 2000 characters.")
        if state == "superseded" and not superseded_by:
            raise ValueError("A superseded memory must identify its replacement.")
        if state != "superseded" and superseded_by is not None:
            raise ValueError("Only a superseded memory may identify a replacement.")
        if superseded_by == memory_id:
            raise ValueError("A memory cannot supersede itself.")
        start = _timestamp(valid_from, "valid_from")
        end = _timestamp(valid_until, "valid_until")
        if start and end and end < start:
            raise ValueError("valid_until cannot precede valid_from.")
        now = _now()
        with closing(self._connect()) as db:
            if db.execute(
                "SELECT 1 FROM memories WHERE id=?", (memory_id,)
            ).fetchone() is None:
                raise KeyError(memory_id)
            if superseded_by and db.execute(
                "SELECT 1 FROM memories WHERE id=?", (superseded_by,)
            ).fetchone() is None:
                raise KeyError(superseded_by)
            db.execute(
                """
                INSERT INTO memory_temporal(
                    memory_id, state, valid_from, valid_until, recorded_at,
                    superseded_by, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    state=excluded.state,
                    valid_from=excluded.valid_from,
                    valid_until=excluded.valid_until,
                    recorded_at=excluded.recorded_at,
                    superseded_by=excluded.superseded_by,
                    note=excluded.note
                """,
                (memory_id, state, start, end, now, superseded_by, note.strip()),
            )
            db.commit()
            return dict(db.execute(
                "SELECT * FROM memory_temporal WHERE memory_id=?", (memory_id,)
            ).fetchone())

    def add_derivation(
        self, derived_memory_id: str, source_memory_ids: list[str],
    ) -> int:
        """Register a model-derived record; it remains pending review."""
        if (
            not isinstance(source_memory_ids, list)
            or not source_memory_ids
            or len(source_memory_ids) > 100
            or any(not isinstance(item, str) or not item for item in source_memory_ids)
            or len(source_memory_ids) != len(set(source_memory_ids))
        ):
            raise ValueError("Provide 1 to 100 unique, non-empty source memory IDs.")
        if not isinstance(derived_memory_id, str) or not derived_memory_id:
            raise ValueError("derived_memory_id must be a non-empty string.")
        if derived_memory_id in source_memory_ids:
            raise ValueError("A derived memory cannot cite itself.")
        with closing(self._connect()) as db:
            ids = {row[0] for row in db.execute(
                "SELECT id FROM memories WHERE id IN (%s)" %
                ",".join("?" for _ in [derived_memory_id, *source_memory_ids]),
                [derived_memory_id, *source_memory_ids],
            )}
            if derived_memory_id not in ids or not set(source_memory_ids) <= ids:
                raise KeyError("Derived record and every source must already exist.")
            now = _now()
            db.executemany("""
                INSERT INTO memory_derivations(
                    derived_memory_id, source_memory_id, state, created_at
                ) VALUES (?, ?, 'pending', ?)
                ON CONFLICT(derived_memory_id, source_memory_id) DO NOTHING
            """, [(derived_memory_id, source_id, now) for source_id in source_memory_ids])
            db.commit()
            return len(source_memory_ids)

    def review_derivation(self, derived_memory_id: str, decision: str) -> int:
        if not isinstance(decision, str) or decision not in {"accepted", "rejected"}:
            raise ValueError("decision must be accepted or rejected.")
        with closing(self._connect()) as db:
            cursor = db.execute("""
                UPDATE memory_derivations SET state=?
                WHERE derived_memory_id=? AND state='pending'
            """, (decision, derived_memory_id))
            if decision == "accepted" and cursor.rowcount:
                current = db.execute(
                    "SELECT memory_key FROM memories WHERE id=?",
                    (derived_memory_id,),
                ).fetchone()
                memory_key = current["memory_key"] if current is not None else None
                if (
                    isinstance(memory_key, str)
                    and memory_key.startswith("consolidated.")
                    and memory_key.count(".") == 2
                ):
                    group_prefix = memory_key.rsplit(".", 1)[0] + "."
                    previous = db.execute(
                        """
                        SELECT m.id
                        FROM memories AS m
                        WHERE m.id != ?
                          AND m.memory_type='inferred_pattern'
                          AND m.memory_key LIKE ?
                          AND EXISTS (
                              SELECT 1 FROM memory_derivations AS d
                              WHERE d.derived_memory_id=m.id AND d.state='accepted'
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM memory_derivations AS d
                              WHERE d.derived_memory_id=m.id AND d.state!='accepted'
                          )
                        """,
                        (derived_memory_id, group_prefix + "%"),
                    ).fetchall()
                    now = _now()
                    for previous_row in previous:
                        db.execute(
                            """
                            INSERT INTO memory_temporal(
                                memory_id, state, recorded_at, superseded_by, note
                            ) VALUES (?, 'superseded', ?, ?, ?)
                            ON CONFLICT(memory_id) DO UPDATE SET
                                state='superseded',
                                recorded_at=excluded.recorded_at,
                                superseded_by=excluded.superseded_by,
                                note=excluded.note
                            """,
                            (
                                previous_row["id"],
                                now,
                                derived_memory_id,
                                "A newer reviewed consolidation replaced this summary.",
                            ),
                        )
            db.commit()
            if cursor.rowcount == 0:
                exists = db.execute(
                    "SELECT 1 FROM memory_derivations WHERE derived_memory_id=?",
                    (derived_memory_id,),
                ).fetchone()
                if exists is None:
                    raise KeyError(derived_memory_id)
            return cursor.rowcount

    def derivation_sources(self, derived_memory_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute("""
                SELECT d.source_memory_id, d.state, d.created_at,
                       m.memory_type, m.subject, m.content, m.source_conversation_id,
                       m.source_message_id, m.provenance, m.confidence
                FROM memory_derivations d
                JOIN memories m ON m.id=d.source_memory_id
                WHERE d.derived_memory_id=?
                ORDER BY d.created_at, d.source_memory_id
            """, (derived_memory_id,)).fetchall()]

    def list_commitments(self, *, state: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        if not isinstance(state, str) or state not in {*COMMITMENT_STATES, "all"}:
            raise ValueError("Unsupported commitment state.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        with closing(self._connect()) as db:
            if state == "all":
                rows = db.execute("""
                    SELECT * FROM memory_commitments
                    ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, created_at
                    LIMIT ?
                """, (limit,))
            else:
                rows = db.execute("""
                    SELECT * FROM memory_commitments WHERE state=?
                    ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, created_at
                    LIMIT ?
                """, (state, limit))
            return [dict(row) for row in rows.fetchall()]

    def create_commitment(
        self, title: str, *, description: str = "", due_at: str | None = None,
        recurrence: str | None = None, source_memory_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 240:
            raise ValueError("title must contain between 1 and 240 characters.")
        if not isinstance(description, str) or len(description) > 4000:
            raise ValueError("description must be at most 4000 characters.")
        if recurrence is not None and (not isinstance(recurrence, str) or len(recurrence) > 200):
            raise ValueError("recurrence must be at most 200 characters.")
        if source_memory_id is not None and (
            not isinstance(source_memory_id, str) or not source_memory_id
        ):
            raise ValueError("source_memory_id must be a non-empty string or None.")
        due = _timestamp(due_at, "due_at")
        now, item_id = _now(), str(uuid.uuid4())
        with closing(self._connect()) as db:
            if source_memory_id and db.execute(
                "SELECT 1 FROM memories WHERE id=?", (source_memory_id,)
            ).fetchone() is None:
                raise KeyError(source_memory_id)
            db.execute("""
                INSERT INTO memory_commitments(
                    id,title,description,due_at,recurrence,state,source_memory_id,created_at,updated_at
                ) VALUES (?,?,?,?,?,'open',?,?,?)
            """, (item_id, title.strip(), description.strip(), due, recurrence,
                  source_memory_id, now, now))
            db.commit()
            return dict(db.execute(
                "SELECT * FROM memory_commitments WHERE id=?", (item_id,)
            ).fetchone())

    def update_commitment(self, commitment_id: str, state: str) -> dict[str, Any]:
        if not isinstance(state, str) or state not in COMMITMENT_STATES:
            raise ValueError(f"Unsupported commitment state: {state}")
        with closing(self._connect()) as db:
            cursor = db.execute("""
                UPDATE memory_commitments SET state=?, updated_at=? WHERE id=?
            """, (state, _now(), commitment_id))
            if cursor.rowcount == 0:
                raise KeyError(commitment_id)
            db.commit()
            return dict(db.execute(
                "SELECT * FROM memory_commitments WHERE id=?", (commitment_id,)
            ).fetchone())
