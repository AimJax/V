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

from v.memory.models import Memory, MemoryLink


MEMORY_TYPES = {
    "profile",
    "preference",
    "episodic",
    "procedural",
    "relationship",
    "project",
    "fact",
    "inferred_pattern",
}

PROVENANCE_TYPES = {"explicit", "inferred"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalize_subject(value: str) -> str:
    return " ".join(value.split()).casefold()


GENERIC_SUBJECT_KEYS = {"", "user", "the user", "self", "myself", "me"}


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

    SCHEMA_VERSION = 6

    def __init__(
        self,
        database_path: Path | str,
        *,
        read_only: bool = False,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.read_only = read_only

        self._has_source_created_at = True
        self._has_memory_links = True
        self._has_memory_evidence = True
        if read_only:
            if not self.database_path.is_file():
                raise FileNotFoundError(
                    f"Memory database does not exist: {self.database_path}"
                )
            # Detect schema capabilities without applying migrations or writes.
            with closing(self._connect()) as connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(memories)")
                }
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            if not columns:
                raise RuntimeError(
                    f"Memory database has no memories table: {self.database_path}"
                )
            self._has_source_created_at = "source_created_at" in columns
            self._has_memory_links = "memory_links" in tables
            self._has_memory_evidence = "memory_evidence" in tables
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
                            'procedural',
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

                CREATE TABLE IF NOT EXISTS memory_links (
                    memory_a_id TEXT NOT NULL,
                    memory_b_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL CHECK (
                        relation_type IN ('same_topic', 'co_mentioned', 'same_timeline')
                    ),
                    basis TEXT NOT NULL CHECK (
                        basis IN ('subject_key', 'source_message', 'episodic_key')
                    ),
                    confidence REAL NOT NULL CHECK (
                        confidence >= 0 AND confidence <= 1
                    ),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (memory_a_id, memory_b_id, relation_type),
                    CHECK (memory_a_id < memory_b_id),
                    FOREIGN KEY (memory_a_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (memory_b_id) REFERENCES memories(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_memory_links_b
                    ON memory_links(memory_b_id, relation_type);

                -- Inferred patterns must retain explicit, independently sourced evidence.
                CREATE TABLE IF NOT EXISTS memory_evidence (
                    pattern_memory_id TEXT NOT NULL,
                    source_memory_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (pattern_memory_id, source_memory_id),
                    CHECK (pattern_memory_id != source_memory_id),
                    FOREIGN KEY (pattern_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_memory_evidence_source
                    ON memory_evidence(source_memory_id, pattern_memory_id);

                -- A derived pattern is removed when its supporting evidence no longer
                -- meets the minimum independent-source requirement.
                CREATE TRIGGER IF NOT EXISTS memory_evidence_cleanup
                AFTER DELETE ON memory_evidence
                BEGIN
                    DELETE FROM memories
                    WHERE id = OLD.pattern_memory_id
                      AND memory_type = 'inferred_pattern'
                      AND provenance = 'inferred'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM memory_evidence AS e
                          JOIN memories AS source ON source.id = e.source_memory_id
                          WHERE e.pattern_memory_id = OLD.pattern_memory_id
                          GROUP BY e.pattern_memory_id
                          HAVING COUNT(DISTINCT source.source_message_id) >= 3
                             AND COUNT(DISTINCT source.source_conversation_id) >= 2
                      );
                END;

                -- Corrections to original statements invalidate derived conclusions.
                CREATE TRIGGER IF NOT EXISTS memory_evidence_source_update
                AFTER UPDATE OF memory_type, provenance, content, evidence, subject
                ON memories
                WHEN OLD.memory_type != 'inferred_pattern'
                BEGIN
                    DELETE FROM memories
                    WHERE id IN (
                        SELECT pattern_memory_id
                        FROM memory_evidence
                        WHERE source_memory_id = OLD.id
                    );
                END;

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

            if "subject_key" not in columns:
                connection.execute(
                    "ALTER TABLE memories ADD COLUMN subject_key TEXT NOT NULL DEFAULT ''"
                )

            # Normalize existing subjects once, preserving original display values.
            subject_rows = connection.execute(
                "SELECT id, subject FROM memories WHERE subject_key = ''"
            ).fetchall()
            for subject_row in subject_rows:
                connection.execute(
                    "UPDATE memories SET subject_key = ? WHERE id = ?",
                    (_normalize_subject(subject_row["subject"]), subject_row["id"]),
                )

            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_subject_key "
                "ON memories(subject_key)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_source_message "
                "ON memories(source_conversation_id, source_message_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_episodic_key "
                "ON memories(memory_key) WHERE memory_type = 'episodic'"
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

            schema_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
            if (
                version < self.SCHEMA_VERSION
                and schema_row is not None
                and "'procedural'" not in schema_row["sql"]
            ):
                self._migrate_procedural_memory_type(connection)

            if version < self.SCHEMA_VERSION:
                self._rebuild_all_relationships(connection)

            connection.execute(
                f"PRAGMA user_version = {self.SCHEMA_VERSION}"
            )
            connection.commit()

        with closing(self._connect()) as continuity_connection:
            tables = {
                row["name"]
                for row in continuity_connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        if "memory_temporal" in tables:
            from v.memory.continuity import ContinuityStore

            ContinuityStore(self.database_path)

    @staticmethod
    def _migrate_procedural_memory_type(connection: sqlite3.Connection) -> None:
        """Rebuild the constrained memory table while preserving dependent data."""
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA legacy_alter_table = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            for trigger in (
                "memories_ai",
                "memories_ad",
                "memories_au",
                "memory_evidence_source_update",
                "continuity_source_changed",
                "continuity_memory_delete",
            ):
                connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")

            connection.execute("ALTER TABLE memories RENAME TO memories_old")
            connection.execute(
                """
                CREATE TABLE memories (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL CHECK (
                        memory_type IN (
                            'profile', 'preference', 'episodic', 'procedural',
                            'relationship', 'project', 'fact', 'inferred_pattern'
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
                    importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
                    source_conversation_id TEXT,
                    source_message_id INTEGER,
                    source_created_at TEXT,
                    evidence TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_confirmed_at TEXT,
                    subject_key TEXT NOT NULL DEFAULT ''
                )
                """
            )
            fields = (
                "id, memory_type, subject, content, memory_key, provenance, confidence, "
                "importance, source_conversation_id, source_message_id, source_created_at, "
                "evidence, created_at, updated_at, last_confirmed_at, subject_key"
            )
            connection.execute(
                f"INSERT INTO memories ({fields}) SELECT {fields} FROM memories_old"
            )
            connection.execute("DROP TABLE memories_old")

            connection.execute(
                """
                CREATE UNIQUE INDEX idx_memories_key
                    ON memories(memory_key)
                    WHERE memory_key IS NOT NULL AND memory_type != 'episodic'
                """
            )
            connection.execute("CREATE INDEX idx_memories_type ON memories(memory_type)")
            connection.execute(
                "CREATE INDEX idx_memories_provenance ON memories(provenance)"
            )
            connection.execute(
                "CREATE INDEX idx_memories_importance ON memories(importance DESC)"
            )
            connection.execute(
                "CREATE INDEX idx_memories_subject_key ON memories(subject_key)"
            )
            connection.execute(
                "CREATE INDEX idx_memories_source_message "
                "ON memories(source_conversation_id, source_message_id)"
            )
            connection.execute(
                "CREATE INDEX idx_memories_episodic_key "
                "ON memories(memory_key) WHERE memory_type='episodic'"
            )
            connection.execute(
                """
                CREATE TRIGGER memories_ai
                AFTER INSERT ON memories
                BEGIN
                    INSERT INTO memories_fts(rowid, content, subject)
                    VALUES (new.rowid, new.content, new.subject);
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER memories_ad
                AFTER DELETE ON memories
                BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, subject)
                    VALUES ('delete', old.rowid, old.content, old.subject);
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER memories_au
                AFTER UPDATE ON memories
                BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, subject)
                    VALUES ('delete', old.rowid, old.content, old.subject);
                    INSERT INTO memories_fts(rowid, content, subject)
                    VALUES (new.rowid, new.content, new.subject);
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER memory_evidence_source_update
                AFTER UPDATE OF memory_type, provenance, content, evidence, subject
                ON memories
                WHEN OLD.memory_type != 'inferred_pattern'
                BEGIN
                    DELETE FROM memories
                    WHERE id IN (
                        SELECT pattern_memory_id
                        FROM memory_evidence
                        WHERE source_memory_id = OLD.id
                    );
                END
                """
            )
            connection.execute(
                "INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA legacy_alter_table = OFF")
            connection.execute("PRAGMA foreign_keys = ON")

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                "Memory type migration produced foreign-key violations."
            )

    @staticmethod
    def _insert_memory_link(connection, memory_a_id, memory_b_id,
                             relation_type, basis, created_at) -> None:
        if memory_a_id == memory_b_id:
            return
        first, second = sorted((memory_a_id, memory_b_id))
        connection.execute(
            """
            INSERT OR IGNORE INTO memory_links (
                memory_a_id, memory_b_id, relation_type, basis,
                confidence, created_at
            ) VALUES (?, ?, ?, ?, 1.0, ?)
            """,
            (first, second, relation_type, basis, created_at),
        )

    @classmethod
    def _refresh_memory_links(cls, connection, memory_id: str) -> None:
        row = connection.execute(
            """
            SELECT id, memory_type, subject_key, memory_key,
                   source_conversation_id, source_message_id
            FROM memories WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()
        if row is None:
            return
        connection.execute(
            "DELETE FROM memory_links WHERE memory_a_id = ? OR memory_b_id = ?",
            (memory_id, memory_id),
        )
        now = _timestamp()
        subject_key = row["subject_key"] or ""
        if subject_key and subject_key not in GENERIC_SUBJECT_KEYS:
            matches = connection.execute(
                """
                SELECT id FROM memories
                WHERE subject_key = ? AND id != ?
                ORDER BY importance DESC, updated_at DESC LIMIT 50
                """,
                (subject_key, memory_id),
            ).fetchall()
            for match in matches:
                cls._insert_memory_link(
                    connection, memory_id, match["id"],
                    "same_topic", "subject_key", now,
                )
        if row["source_message_id"] is not None:
            matches = connection.execute(
                """
                SELECT id FROM memories
                WHERE source_conversation_id IS ?
                  AND source_message_id = ? AND id != ?
                ORDER BY importance DESC, created_at DESC LIMIT 50
                """,
                (row["source_conversation_id"], row["source_message_id"], memory_id),
            ).fetchall()
            for match in matches:
                cls._insert_memory_link(
                    connection, memory_id, match["id"],
                    "co_mentioned", "source_message", now,
                )
        if row["memory_type"] == "episodic" and row["memory_key"]:
            matches = connection.execute(
                """
                SELECT id FROM memories
                WHERE memory_type = 'episodic'
                  AND memory_key = ? AND id != ?
                ORDER BY source_created_at DESC, created_at DESC LIMIT 100
                """,
                (row["memory_key"], memory_id),
            ).fetchall()
            for match in matches:
                cls._insert_memory_link(
                    connection, memory_id, match["id"],
                    "same_timeline", "episodic_key", now,
                )

    @classmethod
    def _rebuild_all_relationships(cls, connection) -> None:
        connection.execute("DELETE FROM memory_links")
        rows = connection.execute(
            "SELECT id FROM memories ORDER BY created_at ASC, id ASC"
        ).fetchall()
        for row in rows:
            cls._refresh_memory_links(connection, row["id"])

    def list_memory_links(self, memory_id: str, *,
                          relation_types: tuple[str, ...] | None = None,
                          limit: int = 50) -> list[MemoryLink]:
        if limit < 1:
            raise ValueError("Memory-link limit must be positive.")
        if not self._has_memory_links:
            return []
        allowed = {"same_topic", "co_mentioned", "same_timeline"}
        if relation_types is not None:
            relation_types = tuple(dict.fromkeys(relation_types))
            if not set(relation_types) <= allowed:
                raise ValueError("Unsupported memory relationship type.")
            if not relation_types:
                return []
        conditions = ["(memory_a_id = ? OR memory_b_id = ?)"]
        parameters: list[object] = [memory_id, memory_id]
        if relation_types is not None:
            conditions.append(
                "relation_type IN (" + ",".join("?" for _ in relation_types) + ")"
            )
            parameters.extend(relation_types)
        parameters.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT memory_a_id, memory_b_id, relation_type,
                       basis, confidence, created_at
                FROM memory_links
                WHERE {" AND ".join(conditions)}
                ORDER BY CASE relation_type
                    WHEN 'same_topic' THEN 0
                    WHEN 'co_mentioned' THEN 1 ELSE 2 END,
                    created_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [
            MemoryLink(
                memory_a_id=row["memory_a_id"], memory_b_id=row["memory_b_id"],
                relation_type=row["relation_type"], basis=row["basis"],
                confidence=row["confidence"], created_at=row["created_at"],
            )
            for row in rows
        ]

    def list_related_memories(self, memory_id: str, *,
                              relation_types: tuple[str, ...] | None = None,
                              limit: int = 20) -> list[Memory]:
        if limit < 1:
            raise ValueError("Related-memory limit must be positive.")
        if not self._has_memory_links:
            return []
        allowed = {"same_topic", "co_mentioned", "same_timeline"}
        if relation_types is not None:
            relation_types = tuple(dict.fromkeys(relation_types))
            if not set(relation_types) <= allowed:
                raise ValueError("Unsupported memory relationship type.")
            if not relation_types:
                return []
        conditions = ["(l.memory_a_id = ? OR l.memory_b_id = ?)"]
        parameters: list[object] = [memory_id, memory_id]
        if relation_types is not None:
            conditions.append(
                "l.relation_type IN (" + ",".join("?" for _ in relation_types) + ")"
            )
            parameters.extend(relation_types)
        parameters.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {self._memory_columns("m")}
                FROM memory_links AS l
                JOIN memories AS m ON m.id = CASE
                    WHEN l.memory_a_id = ? THEN l.memory_b_id
                    ELSE l.memory_a_id END
                WHERE {" AND ".join(conditions)}
                ORDER BY CASE l.relation_type
                    WHEN 'same_topic' THEN 0
                    WHEN 'co_mentioned' THEN 1 ELSE 2 END,
                    m.importance DESC, m.updated_at DESC
                LIMIT ?
                """,
                [memory_id, *parameters],
            ).fetchall()
        return [self._from_row(row) for row in rows if row is not None]

    @staticmethod
    def _validated_pattern_sources(connection, evidence_memory_ids: list[str]):
        ids = list(dict.fromkeys(evidence_memory_ids))
        if len(ids) < 3:
            raise ValueError("An inferred pattern requires at least three supporting memories.")
        if any(not isinstance(item, str) or not item for item in ids):
            raise ValueError("Evidence memory IDs must be non-empty strings.")

        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute(
            f"""
            SELECT id, memory_type, provenance, source_message_id,
                   source_conversation_id
            FROM memories
            WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        if len(rows) != len(ids):
            raise ValueError("Every supporting memory must exist.")
        if any(
            row["provenance"] != "explicit"
            or row["memory_type"] == "inferred_pattern"
            or row["source_message_id"] is None
            or not row["source_conversation_id"]
            for row in rows
        ):
            raise ValueError(
                "Pattern evidence must come from explicit memories with original message sources."
            )

        distinct_messages = {row["source_message_id"] for row in rows}
        distinct_conversations = {row["source_conversation_id"] for row in rows}
        if len(distinct_messages) < 3 or len(distinct_conversations) < 2:
            raise ValueError(
                "An inferred pattern requires three distinct source messages across at least two conversations."
            )
        return rows

    def create_inferred_pattern(
        self,
        *,
        content: str,
        subject: str,
        memory_key: str,
        confidence: float,
        importance: int,
        evidence_memory_ids: list[str],
    ) -> Memory:
        """Create a derived pattern with auditable links to explicit memories."""
        data: dict[str, Any] = {
            "content": content,
            "memory_type": "inferred_pattern",
            "subject": subject,
            "memory_key": memory_key,
            "provenance": "inferred",
            "confidence": confidence,
            "importance": importance,
            "evidence": None,
        }
        _validate_fields(data)
        if not data["memory_key"]:
            raise ValueError("An inferred pattern requires a stable memory key.")
        if data["confidence"] < 0.90:
            raise ValueError("Inferred-pattern confidence must be at least 0.90.")
        if data["importance"] < 3:
            raise ValueError("Inferred patterns must have importance of at least 3.")

        memory_id = uuid.uuid4().hex
        now = _timestamp()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._validated_pattern_sources(connection, evidence_memory_ids)
                    connection.execute(
                        """
                        INSERT INTO memories (
                            id, memory_type, subject, content, memory_key,
                            provenance, confidence, importance,
                            source_conversation_id, source_message_id,
                            source_created_at, evidence, created_at, updated_at,
                            last_confirmed_at, subject_key
                        )
                        VALUES (?, 'inferred_pattern', ?, ?, ?, 'inferred',
                                ?, ?, NULL, NULL, NULL, NULL, ?, ?, NULL, ?)
                        """,
                        (
                            memory_id,
                            data["subject"],
                            data["content"],
                            data["memory_key"],
                            data["confidence"],
                            data["importance"],
                            now,
                            now,
                            _normalize_subject(data["subject"]),
                        ),
                    )
                    for source_id in dict.fromkeys(evidence_memory_ids):
                        connection.execute(
                            """
                            INSERT INTO memory_evidence (
                                pattern_memory_id, source_memory_id, created_at
                            ) VALUES (?, ?, ?)
                            """,
                            (memory_id, source_id, now),
                        )
                    continuity_table = connection.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type='table' AND name='memory_derivations'"
                    ).fetchone()
                    if continuity_table is not None:
                        connection.executemany(
                            """
                            INSERT INTO memory_derivations(
                                derived_memory_id, source_memory_id, state, created_at
                            ) VALUES (?, ?, 'pending', ?)
                            """,
                            [
                                (memory_id, source_id, now)
                                for source_id in dict.fromkeys(evidence_memory_ids)
                            ],
                        )
                    self._refresh_memory_links(connection, memory_id)
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "The inferred pattern conflicts with an existing memory."
            ) from error

        result = self.get_memory(memory_id)
        if result is None:
            raise RuntimeError("Created inferred pattern could not be retrieved.")
        return result

    def attach_memory_evidence(
        self,
        pattern_memory_id: str,
        evidence_memory_ids: list[str],
    ) -> int:
        """Attach additional explicit sources to an existing inferred pattern."""
        if not self._has_memory_evidence:
            raise RuntimeError("This memory database does not support evidence links.")
        now = _timestamp()
        with closing(self._connect()) as connection:
            with connection:
                pattern = connection.execute(
                    """
                    SELECT memory_type, provenance
                    FROM memories WHERE id = ?
                    """,
                    (pattern_memory_id,),
                ).fetchone()
                if (
                    pattern is None
                    or pattern["memory_type"] != "inferred_pattern"
                    or pattern["provenance"] != "inferred"
                ):
                    raise ValueError("Target must be an existing inferred pattern.")

                existing = connection.execute(
                    """
                    SELECT source_memory_id FROM memory_evidence
                    WHERE pattern_memory_id = ?
                    """,
                    (pattern_memory_id,),
                ).fetchall()
                all_ids = [
                    row["source_memory_id"] for row in existing
                ] + list(evidence_memory_ids)
                self._validated_pattern_sources(connection, all_ids)
                inserted = 0
                for source_id in dict.fromkeys(evidence_memory_ids):
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO memory_evidence (
                            pattern_memory_id, source_memory_id, created_at
                        ) VALUES (?, ?, ?)
                        """,
                        (pattern_memory_id, source_id, now),
                    )
                    inserted += cursor.rowcount
        return inserted

    def list_memory_evidence(self, pattern_memory_id: str) -> list[Memory]:
        """Return the explicit memories supporting one inferred pattern."""
        if not self._has_memory_evidence:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {self._memory_columns("m")}
                FROM memory_evidence AS e
                JOIN memories AS m ON m.id = e.source_memory_id
                WHERE e.pattern_memory_id = ?
                ORDER BY m.source_created_at, m.created_at, m.id
                """,
                (pattern_memory_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows if row is not None]

    def count_inferred_patterns(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM memories
                WHERE memory_type = 'inferred_pattern'
                  AND provenance = 'inferred'
                """
            ).fetchone()
        return int(row[0])

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
        subject_key = _normalize_subject(subject)
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
                            last_confirmed_at, subject_key
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            subject_key,
                        ),
                    )
                    self._refresh_memory_links(connection, memory_id)
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
        if "subject" in changes:
            changes["subject_key"] = _normalize_subject(changes["subject"])

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
                    if set(changes) & {"memory_type", "memory_key", "subject", "subject_key"}:
                        self._refresh_memory_links(connection, memory_id)

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