"""Persistent vector cache for local semantic memory retrieval."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class EmbeddingStore:
    """Store embeddings tied to the complete memory document."""

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
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (memory_id)
                        REFERENCES memories(id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model
                ON memory_embeddings(model)
                """
            )
            connection.commit()

    @staticmethod
    def _content_hash(
        memory_type: str,
        subject: str,
        content: str,
    ) -> str:
        document = json_document = "\n".join(
            (memory_type, subject, content)
        )

        return hashlib.sha256(
            json_document.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _encode_vector(vector: list[float]) -> bytes:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError("Embedding vector cannot be empty.")

        values = []

        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Embedding values must be numeric.")

            number = float(value)

            if not math.isfinite(number):
                raise ValueError("Embedding values must be finite.")

            values.append(number)

        return struct.pack(f"<{len(values)}f", *values)

    @staticmethod
    def _decode_vector(blob: bytes, dimensions: int) -> tuple[float, ...]:
        if dimensions < 1 or len(blob) != dimensions * 4:
            raise ValueError("Stored embedding has invalid dimensions.")

        vector = struct.unpack(f"<{dimensions}f", blob)

        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Stored embedding contains invalid values.")

        return vector

    def put(
        self,
        memory_id: str,
        model: str,
        vector: list[float],
    ) -> None:
        """Save an embedding tied to the current memory document."""
        if not model or not model.strip():
            raise ValueError("Embedding model identifier is required.")

        blob = self._encode_vector(vector)
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    """
                    SELECT content, memory_type, subject
                    FROM memories
                    WHERE id = ?
                    """,
                    (memory_id,),
                ).fetchone()

                if row is None:
                    raise KeyError(f"Memory not found: {memory_id}")

                digest = self._content_hash(
                    row["memory_type"],
                    row["subject"],
                    row["content"],
                )

                connection.execute(
                    """
                    INSERT INTO memory_embeddings (
                        memory_id, model, dimensions,
                        content_hash, vector, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        model = excluded.model,
                        dimensions = excluded.dimensions,
                        content_hash = excluded.content_hash,
                        vector = excluded.vector,
                        updated_at = excluded.updated_at
                    """,
                    (
                        memory_id,
                        model.strip(),
                        len(vector),
                        digest,
                        blob,
                        now,
                    ),
                )

    def get_valid(self, model: str) -> dict[str, tuple[float, ...]]:
        """Return vectors matching their model and current memory document."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT e.memory_id, e.dimensions, e.vector,
                       e.content_hash, m.content, m.memory_type, m.subject
                FROM memory_embeddings AS e
                JOIN memories AS m ON m.id = e.memory_id
                WHERE e.model = ?
                """,
                (model,),
            ).fetchall()

        results = {}

        for row in rows:
            digest = self._content_hash(
                row["memory_type"],
                row["subject"],
                row["content"],
            )

            if digest != row["content_hash"]:
                continue

            results[row["memory_id"]] = self._decode_vector(
                row["vector"],
                row["dimensions"],
            )

        return results

    def missing_memory_ids(
        self,
        model: str,
        *,
        limit: int = 1000,
    ) -> list[str]:
        if limit < 1:
            raise ValueError("Embedding batch limit must be positive.")

        valid = self.get_valid(model)

        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id FROM memories ORDER BY created_at ASC"
            ).fetchall()

        return [
            row["id"]
            for row in rows
            if row["id"] not in valid
        ][:limit]

    def count(self, model: str | None = None) -> int:
        if model is None:
            with closing(self._connect()) as connection:
                return int(connection.execute(
                    "SELECT COUNT(*) FROM memory_embeddings"
                ).fetchone()[0])

        return len(self.get_valid(model))

    def delete(self, memory_id: str) -> bool:
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?",
                    (memory_id,),
                )

        return cursor.rowcount > 0