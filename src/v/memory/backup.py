"""Validated, versioned JSON backup and restore for V's long-term memories."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile

from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from v.memory.store import MemoryStore, _validate_fields


BACKUP_FORMAT = "v-memory-backup"
BACKUP_VERSION = 2
MAX_BACKUP_BYTES = 10 * 1024 * 1024
MAX_MEMORIES = 10_000

MEMORY_FIELDS = (
    "id",
    "memory_type",
    "subject",
    "content",
    "memory_key",
    "provenance",
    "confidence",
    "importance",
    "source_conversation_id",
    "source_message_id",
    "source_created_at",
    "evidence",
    "created_at",
    "updated_at",
    "last_confirmed_at",
)

LEGACY_MEMORY_FIELDS = tuple(
    field for field in MEMORY_FIELDS if field != "source_created_at"
)


def _valid_timestamp(value: Any, field: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return

    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty ISO-8601 timestamp.")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp.") from error

    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")


def _validate_record(
    record: Any,
    *,
    version: int,
) -> dict[str, Any]:
    expected_fields = (
        LEGACY_MEMORY_FIELDS if version == 1 else MEMORY_FIELDS
    )
    if not isinstance(record, dict) or set(record) != set(expected_fields):
        raise ValueError("Backup contains a memory with an invalid field set.")

    normalized = dict(record)
    if version == 1:
        normalized["source_created_at"] = None

    memory_id = normalized["id"]
    if not isinstance(memory_id, str) or not re.fullmatch(r"[0-9a-f]{32}", memory_id):
        raise ValueError("Memory IDs must be 32-character lowercase hexadecimal values.")

    for field in ("memory_type", "provenance"):
        if not isinstance(normalized[field], str):
            raise ValueError(f"{field} must be a string.")

    if "memory_key" in normalized and (
        normalized["memory_key"] is not None
        and not isinstance(normalized["memory_key"], str)
    ):
        raise ValueError("memory_key must be a string or null.")

    fields = {
        field: normalized[field]
        for field in (
            "memory_type",
            "subject",
            "content",
            "memory_key",
            "provenance",
            "confidence",
            "importance",
            "evidence",
            "last_confirmed_at",
            "source_created_at",
        )
    }
    _validate_fields(fields)
    normalized.update(fields)

    if normalized["source_conversation_id"] is not None and not isinstance(
        normalized["source_conversation_id"], str
    ):
        raise ValueError("source_conversation_id must be a string or null.")

    source_message_id = normalized["source_message_id"]
    if source_message_id is not None and (
        isinstance(source_message_id, bool)
        or not isinstance(source_message_id, int)
        or source_message_id < 1
    ):
        raise ValueError("source_message_id must be a positive integer or null.")

    _valid_timestamp(normalized["created_at"], "created_at")
    _valid_timestamp(normalized["updated_at"], "updated_at")
    _valid_timestamp(
        normalized["source_created_at"],
        "source_created_at",
        optional=True,
    )
    _valid_timestamp(
        normalized["last_confirmed_at"],
        "last_confirmed_at",
        optional=True,
    )
    return normalized


def export_backup(
    store: MemoryStore,
    destination: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[Path, int]:
    """Write a complete memory backup atomically; backups are plaintext JSON."""
    path = Path(destination).expanduser().resolve()

    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Backup destination already exists: {path} (use --overwrite to replace it)"
        )

    with closing(store._connect()) as connection:
        rows = connection.execute(
            f"SELECT {store._memory_columns()} FROM memories ORDER BY created_at, id"
        ).fetchall()

    if len(rows) > MAX_MEMORIES:
        raise ValueError(f"Cannot export more than {MAX_MEMORIES} memories.")

    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "memories": [dict(row) for row in rows],
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")

    if len(encoded) > MAX_BACKUP_BYTES:
        raise ValueError(
            f"Backup exceeds the {MAX_BACKUP_BYTES // (1024 * 1024)} MiB size limit."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())

        if path.exists() and not overwrite:
            raise FileExistsError(f"Backup destination already exists: {path}")

        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return path, len(rows)


def import_backup(
    store: MemoryStore,
    source: Path | str,
) -> tuple[int, int]:
    """Restore a backup as an all-or-nothing merge.

    Existing identical IDs are skipped. An ID or unique-key conflict aborts
    the entire import; existing memories are never overwritten or deleted.
    Returns (restored_count, skipped_identical_count).
    """
    path = Path(source).expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(f"Memory backup not found: {path}")

    size = path.stat().st_size
    if size > MAX_BACKUP_BYTES:
        raise ValueError(
            f"Backup exceeds the {MAX_BACKUP_BYTES // (1024 * 1024)} MiB size limit."
        )

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"Invalid JSON numeric constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Backup must be valid UTF-8 JSON.") from error

    if not isinstance(payload, dict):
        raise ValueError("Backup root must be a JSON object.")

    if payload.get("format") != BACKUP_FORMAT:
        raise ValueError("File is not a V memory backup.")

    version = payload.get("version")
    if version not in {1, BACKUP_VERSION}:
        raise ValueError(
            f"Unsupported memory backup version: {version!r}"
        )

    _valid_timestamp(payload.get("exported_at"), "exported_at")
    records = payload.get("memories")

    if not isinstance(records, list):
        raise ValueError("Backup memories must be a JSON array.")

    if len(records) > MAX_MEMORIES:
        raise ValueError(f"Cannot import more than {MAX_MEMORIES} memories.")

    validated = [
        _validate_record(record, version=version)
        for record in records
    ]
    ids = [record["id"] for record in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("Backup contains duplicate memory IDs.")

    keys = [
        record["memory_key"]
        for record in validated
        if record["memory_key"] is not None
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("Backup contains duplicate memory keys.")

    restored = 0
    skipped = 0

    try:
        with closing(store._connect()) as connection:
            with connection:
                for record in validated:
                    existing = connection.execute(
                        f"""
                        SELECT {store._memory_columns()}
                        FROM memories
                        WHERE id = ?
                        """,
                        (record["id"],),
                    ).fetchone()

                    if existing is not None:
                        if dict(existing) == record:
                            skipped += 1
                            continue
                        raise ValueError(
                            f"Memory ID conflict; no data was imported: {record['id']}"
                        )

                    connection.execute(
                        f"""
                        INSERT INTO memories ({store._memory_columns()})
                        VALUES ({", ".join("?" for _ in MEMORY_FIELDS)})
                        """,
                        [record[field] for field in MEMORY_FIELDS],
                    )
                    restored += 1
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed: memories.memory_key" in str(error):
            raise ValueError(
                "Memory-key conflict; no data was imported."
            ) from error
        raise ValueError(
            "Database constraint conflict; no data was imported."
        ) from error

    return restored, skipped
