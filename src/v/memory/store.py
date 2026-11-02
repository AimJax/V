"""SQLite-backed long-term memory storage and retrieval."""

from __future__ import annotations

import math
import re
import sqlite3
import uuid

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v.memory.models import Memory


MEMORY_TYPES = {
    "profile",
    "preference",
    "episodic",
    "relationship",
    "project",
    "fact",
    "inferred_pattern",
}

PROVENANCE_TYPES = {"explicit", "inferred"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalize_key(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _validate_fields(data: dict[str, Any]) -> None:
    if "memory_type" in data:
        if data["memory_type"] not in MEMORY_TYPES:
            raise ValueError(
                f"Unsupported memory type: {data['memory_type']}"
            )

    if "provenance" in data:
        if data["provenance"] not in PROVENANCE_TYPES:
            raise ValueError(
                f"Unsupported provenance: {data['provenance']}"
            )

    if "content" in data:
        content = data["content"]

        if not isinstance(content, str) or not content.strip():
            raise ValueError("Memory content cannot be empty.")

        data["content"] = content.strip()

    if "subject" in data:
        if not isinstance(data["subject"], str):
            raise TypeError("Memory subject must be a string.")

        data["subject"] = data["subject"].strip()

    if "memory_key" in data:
        memory_key = data["memory_key"]
        if memory_key is not None and not isinstance(memory_key, str):
            raise TypeError("Memory key must be a string or None.")
        data["memory_key"] = _normalize_key(memory_key)

    if "confidence" in data:
        if isinstance(data["confidence"], bool):
            raise ValueError("Confidence must be numeric, not boolean.")

        try:
            confidence = float(data["confidence"])
        except (TypeError, ValueError) as error:
            raise ValueError("Confidence must be numeric.") from error

        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1.")

        data["confidence"] = confidence

    if "importance" in data:
        importance = data["importance"]

        if (
            isinstance(importance, bool)
            or not isinstance(importance, int)
            or not 1 <= importance <= 5
        ):
            raise ValueError("Importance must be an integer from 1 to 5.")

    if "evidence" in data:
        evidence = data["evidence"]

        if evidence is not None and not isinstance(evidence, str):
            raise TypeError("Evidence must be a string or None.")

    if "source_created_at" in data:
        source_created_at = data["source_created_at"]
        if source_created_at is not None:
            if not isinstance(source_created_at, str) or not source_created_at:
                raise ValueError(
                    "source_created_at must be a timezone-aware ISO-8601 timestamp or None."
                )
            try:
                parsed_source_date = datetime.fromisoformat(
                    source_created_at.replace("Z", "+00:00")
                )
            except ValueError as error:
                raise ValueError(
                    "source_created_at must be a valid ISO-8601 timestamp."
                ) from error
            if parsed_source_date.tzinfo is None:
                raise ValueError(
                    "source_created_at must include a timezone."
                )

    if "last_confirmed_at" in data:
        confirmed = data["last_confirmed_at"]

        if confirmed is not None and not isinstance(confirmed, str):
            raise TypeError("last_confirmed_at must be a string or None.")


class MemoryStore:
    """Manage V's local memories.

    Memories are physically deleted when delete_memory() is called.
    This initial implementation does not retain a hidden deletion archive.
    """

    SCHEMA_VERSION = 3

    def __init__(
        self,
        database_path: Path | str,
        *,
        read_only: bool = False,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.read_only = read_only

        self._has_source_created_at = True
        if read_only:
            if not self.database_path.is_file():
                raise FileNotFoundError(
                    f"Memory database does not exist: {self.database_path}"
                )
            # Older databases may predate the source_created_at migration.
            # Detect that schema without applying any migration or write.
            with closing(self._connect()) as connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(memories)")
                }
            if not columns:
                raise RuntimeError(
                    f"Memory database has no memories table: {self.database_path}"
                )
            self._has_source_created_at = "source_created_at" in columns
        else:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            database_uri = f"{self.database_path.as_uri()}?mode=ro"
            connection = sqlite3.connect(
                database_uri,
                uri=True,
                timeout=5.0,
            )
        else:
            connection = sqlite3.connect(
                str(self.database_path),
                timeout=5.0,
            )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")

            version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]

            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"Memory schema version {version} is newer than "
                    f"supported version {self.SCHEMA_VERSION}."
                )

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,

                    memory_type TEXT NOT NULL CHECK (
                        memory_type IN (
                            'profile',
                            'preference',
                            'episodic',
                            'relationship',
                            'project',
                            'fact',
                            'inferred_pattern'
                        )
                    ),

                    subject TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
                    memory_key TEXT,

                    provenance TEXT NOT NULL CHECK (
                        provenance IN ('explicit', 'inferred')
                    ),

                    confidence REAL NOT NULL CHECK (
                        confidence >= 0 AND confidence <= 1
                    ),

                    importance INTEGER NOT NULL CHECK (
                        importance BETWEEN 1 AND 5
                    ),

                    source_conversation_id TEXT,
                    source_message_id INTEGER,
                    source_created_at TEXT,
                    evidence TEXT,

                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_confirmed_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_key
                    ON memories(memory_key)
                    WHERE memory_key IS NOT NULL
                      AND memory_type != 'episodic';

                CREATE INDEX IF NOT EXISTS idx_memories_type
                    ON memories(memory_type);

                CREATE INDEX IF NOT EXISTS idx_memories_provenance
                    ON memories(provenance);

                CREATE INDEX IF NOT EXISTS idx_memories_importance
                    ON memories(importance DESC);

                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(
                    content,
                    subject,
                    content='memories',
                    content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS memories_ai
                AFTER INSERT ON memories
                BEGIN
                    INSERT INTO memories_fts(rowid, content, subject)
                    VALUES (new.rowid, new.content, new.subject);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_ad
                AFTER DELETE ON memories
                BEGIN
                    INSERT INTO memories_fts(
                        memories_fts,
                        rowid,
                        content,
                        subject
                    )
                    VALUES (
                        'delete',
                        old.rowid,
                        old.content,
                        old.subject
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS memories_au
                AFTER UPDATE ON memories
                BEGIN
                    INSERT INTO memories_fts(
                        memories_fts,
                        rowid,
                        content,
                        subject
                    )
                    VALUES (
                        'delete',
                        old.rowid,
                        old.content,
                        old.subject
                    );

                    INSERT INTO memories_fts(rowid, content, subject)
                    VALUES (new.rowid, new.content, new.subject);
                END;
                """
            )

            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(memories)")
            }
            if "source_created_at" not in columns:
                connection.execute(
                    "ALTER TABLE memories ADD COLUMN source_created_at TEXT"
                )

            # Episodic records are dated snapshots, not a single mutable
            # current-value slot. Preserve uniqueness for stable/profile keys
            # while allowing a timeline of episodic memories under one key.
            connection.execute("DROP INDEX IF EXISTS idx_memories_key")
            connection.execute(
                """
                CREATE UNIQUE INDEX idx_memories_key
                ON memories(memory_key)
                WHERE memory_key IS NOT NULL
                  AND memory_type != 'episodic'
                """
            )

            connection.execute(
                f"PRAGMA user_version = {self.SCHEMA_VERSION}"
            )
            connection.commit()

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> Memory | None:
        if row is None:
            return None

        return Memory(
            id=row["id"],
            memory_type=row["memory_type"],
            subject=row["subject"],
            content=row["content"],
            memory_key=row["memory_key"],
            provenance=row["provenance"],
            confidence=row["confidence"],
            importance=row["importance"],
            source_conversation_id=row["source_conversation_id"],
            source_message_id=row["source_message_id"],
            source_created_at=row["source_created_at"],
            evidence=row["evidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_confirmed_at=row["last_confirmed_at"],
        )

    def _memory_columns(self, table_alias: str | None = None) -> str:
        """Return selected memory fields, tolerating pre-timeline read-only DBs."""
        prefix = f"{table_alias}." if table_alias else ""
        source_date = (
            f"{prefix}source_created_at"
            if self._has_source_created_at
            else "NULL AS source_created_at"
        )
        return ", ".join((
            f"{prefix}id",
            f"{prefix}memory_type",
            f"{prefix}subject",
            f"{prefix}content",
            f"{prefix}memory_key",
            f"{prefix}provenance",
            f"{prefix}confidence",
            f"{prefix}importance",
            f"{prefix}source_conversation_id",
            f"{prefix}source_message_id",
            source_date,
            f"{prefix}evidence",
            f"{prefix}created_at",
            f"{prefix}updated_at",
            f"{prefix}last_confirmed_at",
        ))

    def _source_created_at_order_expression(self) -> str:
        return "source_created_at" if self._has_source_created_at else "NULL"

    def create_memory(
        self,
        *,
        content: str,
        memory_type: str = "fact",
        subject: str = "",
        memory_key: str | None = None,
        provenance: str = "explicit",
        confidence: float = 1.0,
        importance: int = 3,
        source_conversation_id: str | None = None,
        source_message_id: int | None = None,
        source_created_at: str | None = None,
        evidence: str | None = None,
    ) -> Memory:
        """Create a memory with source and provenance metadata."""
        data: dict[str, Any] = {
            "content": content,
            "memory_type": memory_type,
            "subject": subject,
            "memory_key": memory_key,
            "provenance": provenance,
            "confidence": confidence,
            "importance": importance,
            "source_created_at": source_created_at,
            "evidence": evidence,
        }

        _validate_fields(data)

        # Use normalized and validated values for database insertion.
        content = data["content"]
        memory_type = data["memory_type"]
        subject = data["subject"]
        memory_key = data["memory_key"]
        provenance = data["provenance"]
        confidence = data["confidence"]
        importance = data["importance"]
        evidence = data["evidence"]

        if (
            source_message_id is not None
            and (
                isinstance(source_message_id, bool)
                or not isinstance(source_message_id, int)
                or source_message_id < 1
            )
        ):
            raise ValueError("source_message_id must be a positive integer.")

        if source_conversation_id is not None:
            if not isinstance(source_conversation_id, str):
                raise TypeError("source_conversation_id must be a string.")

        now = _timestamp()
        memory_id = uuid.uuid4().hex

        last_confirmed = now if provenance == "explicit" else None

        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO memories (
                            id, memory_type, subject, content, memory_key,
                            provenance, confidence, importance,
                            source_conversation_id, source_message_id,
                            source_created_at, evidence, created_at, updated_at,
                            last_confirmed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            memory_id,
                            memory_type,
                            subject,
                            content,
                            memory_key,
                            provenance,
                            confidence,
                            importance,
                            source_conversation_id,
                            source_message_id,
                            source_created_at,
                            evidence,
                            now,
                            now,
                            last_confirmed,
                        ),
                    )
        except sqlite3.IntegrityError as error:
            if memory_key is not None:
                raise ValueError(
                    f"A memory already exists with key: {memory_key}"
                ) from error
            raise

        result = self.get_memory(memory_id)

        if result is None:
            raise RuntimeError("Created memory could not be retrieved.")

        return result

    def get_memory_by_key(self, memory_key: str) -> Memory | None:
        """Look up a memory by its normalized, unique key."""
        normalized = _normalize_key(memory_key)
        if normalized is None:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {self._memory_columns()}
                FROM memories
                WHERE memory_key = ?
                ORDER BY
                    CASE WHEN memory_type = 'episodic' THEN 1 ELSE 0 END,
                    julianday({self._source_created_at_order_expression()}) DESC,
                    importance DESC,
                    updated_at DESC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
        return self._from_row(row)

    def confirm_memory(self, memory_id: str) -> Memory:
        """Record an explicit user confirmation without changing source evidence."""
        return self.update_memory(memory_id, last_confirmed_at=_timestamp())

    def get_memory(self, memory_id: str) -> Memory | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {self._memory_columns()}
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()

        return self._from_row(row)

    def list_memories(
        self,
        *,
        limit: int = 100,
        memory_type: str | None = None,
        provenance: str | None = None,
    ) -> list[Memory]:
        if limit < 1:
            raise ValueError("Memory limit must be positive.")

        if memory_type is not None and memory_type not in MEMORY_TYPES:
            raise ValueError("Unsupported memory type.")

        if provenance is not None and provenance not in PROVENANCE_TYPES:
            raise ValueError("Unsupported provenance.")

        conditions: list[str] = []
        parameters: list[Any] = []

        if memory_type is not None:
            conditions.append("memory_type = ?")
            parameters.append(memory_type)

        if provenance is not None:
            conditions.append("provenance = ?")
            parameters.append(provenance)

        where = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )

        parameters.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {self._memory_columns()}
                FROM memories
                {where}
                ORDER BY
                    CASE WHEN memory_type = 'episodic' THEN 1 ELSE 0 END,
                    CASE WHEN memory_type = 'episodic'
                         THEN julianday({self._source_created_at_order_expression()}) END DESC,
                    importance DESC,
                    updated_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        return [
            self._from_row(row)
            for row in rows
        ]

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[Memory]:
        """Search content and subjects with FTS5.

        All extracted search terms must match. An empty or punctuation-only
        query returns an empty result instead of issuing malformed FTS syntax.
        """
        if limit < 1:
            raise ValueError("Search limit must be positive.")

        terms = re.findall(r"[\w]+", query, flags=re.UNICODE)

        if not terms:
            return []

        match_query = " AND ".join(
            f'"{term.replace(chr(34), chr(34) * 2)}"'
            for term in terms
        )

        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {self._memory_columns("m")}
                FROM memories_fts
                JOIN memories AS m
                    ON m.rowid = memories_fts.rowid
                WHERE memories_fts MATCH ?
                ORDER BY
                    bm25(memories_fts, 2.0, 1.0) ASC,
                    m.importance DESC,
                    m.updated_at DESC
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()

        return [
            self._from_row(row)
            for row in rows
        ]

    def search_memories_any(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[Memory]:
        """Search memories matching at least one meaningful query term."""
        if limit < 1:
            raise ValueError("Search limit must be positive.")

        terms = re.findall(r"[\w]+", query, flags=re.UNICODE)

        if not terms:
            return []

        match_query = " OR ".join(
            f'"{term}"' for term in dict.fromkeys(terms)
        )

        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {self._memory_columns("m")}
                FROM memories_fts
                JOIN memories AS m
                    ON m.rowid = memories_fts.rowid
                WHERE memories_fts MATCH ?
                ORDER BY
                    bm25(memories_fts, 2.0, 1.0) ASC,
                    m.importance DESC,
                    m.updated_at DESC
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()

        return [
            self._from_row(row)
            for row in rows
        ]
    def update_memory(
        self,
        memory_id: str,
        **changes: Any,
    ) -> Memory:
        """Correct or revise an existing memory.

        Only the explicitly supplied, permitted fields are modified.
        The original creation timestamp and source provenance are retained.
        """
        allowed = {
            "memory_type",
            "subject",
            "content",
            "memory_key",
            "provenance",
            "confidence",
            "importance",
            "evidence",
            "last_confirmed_at",
        }

        if not changes:
            existing = self.get_memory(memory_id)

            if existing is None:
                raise KeyError(f"Memory not found: {memory_id}")

            return existing

        unexpected = set(changes) - allowed

        if unexpected:
            raise ValueError(
                f"Unsupported memory fields: {sorted(unexpected)}"
            )

        changes = dict(changes)
        _validate_fields(changes)

        changes["updated_at"] = _timestamp()

        assignments = ", ".join(
            f"{field} = ?" for field in changes
        )

        values = list(changes.values()) + [memory_id]

        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        f"""
                        UPDATE memories
                        SET {assignments}
                        WHERE id = ?
                        """,
                        values,
                    )

                    if cursor.rowcount == 0:
                        raise KeyError(f"Memory not found: {memory_id}")

        except sqlite3.IntegrityError as error:
            raise ValueError(
                "The correction conflicts with an existing memory."
            ) from error

        result = self.get_memory(memory_id)

        if result is None:
            raise RuntimeError("Updated memory could not be retrieved.")

        return result

    def delete_memory(self, memory_id: str) -> bool:
        """Permanently delete a memory and its FTS index entry."""
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM memories WHERE id = ?",
                    (memory_id,),
                )

        return cursor.rowcount > 0

    def count_memories(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM memories"
            ).fetchone()

        return int(row[0])

    def optimize_search_index(self) -> None:
        """Merge FTS index segments after substantial changes."""
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO memories_fts(memories_fts) VALUES ('optimize')"
            )
            connection.commit()