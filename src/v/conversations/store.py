"""SQLite-backed persistent conversation storage."""

from __future__ import annotations

import sqlite3
import uuid

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from v.providers.base import ChatMessage


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class StoredMessage:
    id: int
    conversation_id: str
    role: str
    content: str
    created_at: str

def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ConversationStore:
    """Store conversations locally in a SQLite database."""

    SCHEMA_VERSION = 1

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

            version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]

            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer "
                    f"than supported version {self.SCHEMA_VERSION}."
                )

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (
                        role IN ('user', 'assistant')
                    ),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    idx_messages_conversation_id
                ON messages(conversation_id, id);

                CREATE INDEX IF NOT EXISTS
                    idx_messages_role_id
                ON messages(role, id);

                CREATE INDEX IF NOT EXISTS
                    idx_conversations_updated_at
                ON conversations(updated_at DESC);
                """
            )

            connection.execute(
                f"PRAGMA user_version = {self.SCHEMA_VERSION}"
            )
            connection.commit()

    @staticmethod
    def _to_conversation(row: sqlite3.Row | None) -> Conversation | None:
        if row is None:
            return None

        return Conversation(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_conversation(
        self,
        title: str = "New conversation",
    ) -> Conversation:
        conversation_id = uuid.uuid4().hex
        now = _timestamp()

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO conversations
                        (id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (conversation_id, title, now, now),
                )

        return Conversation(
            id=conversation_id,
            title=title,
            created_at=now,
            updated_at=now,
        )

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()

        return self._to_conversation(row)

    def get_latest_conversation(self) -> Conversation | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()

        return self._to_conversation(row)

    def list_conversations(
        self,
        limit: int = 20,
    ) -> list[Conversation]:
        if limit < 1:
            raise ValueError("Conversation limit must be positive.")

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            Conversation(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> int:
        if role not in {"user", "assistant"}:
            raise ValueError(f"Unsupported stored message role: {role}")

        if not isinstance(content, str) or not content.strip():
            raise ValueError("Message content cannot be empty.")

        now = _timestamp()

        with closing(self._connect()) as connection:
            with connection:
                conversation = connection.execute(
                    """
                    SELECT title
                    FROM conversations
                    WHERE id = ?
                    """,
                    (conversation_id,),
                ).fetchone()

                if conversation is None:
                    raise KeyError(
                        f"Conversation does not exist: {conversation_id}"
                    )

                cursor = connection.execute(
                    """
                    INSERT INTO messages
                        (conversation_id, role, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (conversation_id, role, content, now),
                )
                message_id = int(cursor.lastrowid)

                if role == "user" and conversation["title"] == "New conversation":
                    title = " ".join(content.split())

                    if len(title) > 60:
                        title = title[:57].rstrip() + "..."

                    connection.execute(
                        """
                        UPDATE conversations
                        SET title = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (title or "New conversation", now, conversation_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE conversations
                        SET updated_at = ?
                        WHERE id = ?
                        """,
                        (now, conversation_id),
                    )

        return message_id

    def get_message_record(self, message_id: int) -> StoredMessage | None:
        """Retrieve one stored message with its permanent database ID."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, conversation_id, role, content, created_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

        if row is None:
            return None

        return StoredMessage(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )
    def max_user_message_id(self) -> int:
        """Return the highest user-message ID in the historical snapshot."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM messages WHERE role = 'user'"
            ).fetchone()
        return int(row[0])

    def count_user_messages(self, *, through_id: int | None = None) -> int:
        """Count user messages up to an optional stable ID boundary."""
        with closing(self._connect()) as connection:
            if through_id is None:
                row = connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE role = 'user'"
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE role = 'user' AND id <= ?
                    """,
                    (through_id,),
                ).fetchone()
        return int(row[0])

    def list_user_messages(
        self,
        *,
        after_id: int = 0,
        through_id: int | None = None,
        limit: int = 5,
    ) -> list[StoredMessage]:
        """Read a bounded, ordered page for durable historical reprocessing."""
        if after_id < 0:
            raise ValueError("after_id cannot be negative.")
        if through_id is not None and through_id < after_id:
            return []
        if not 1 <= limit <= 1000:
            raise ValueError("User-message page size must be between 1 and 1000.")

        if through_id is None:
            sql = """
                SELECT id, conversation_id, role, content, created_at
                FROM messages
                WHERE role = 'user' AND id > ?
                ORDER BY id ASC
                LIMIT ?
            """
            parameters = (after_id, limit)
        else:
            sql = """
                SELECT id, conversation_id, role, content, created_at
                FROM messages
                WHERE role = 'user' AND id > ? AND id <= ?
                ORDER BY id ASC
                LIMIT ?
            """
            parameters = (after_id, through_id, limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(sql, parameters).fetchall()

        return [
            StoredMessage(
                id=row["id"],
                conversation_id=row["conversation_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 24,
    ) -> list[ChatMessage]:
        if limit < 1:
            raise ValueError("Message limit must be positive.")

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()

        rows.reverse()

        return [
            ChatMessage(role=row["role"], content=row["content"])
            for row in rows
        ]

    def count_messages(self, conversation_id: str) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()

        return int(row[0])