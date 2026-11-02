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
BACKUP_VERSION = 3
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

    evidence_rows = connection.execute(
        """
        SELECT pattern_memory_id, source_memory_id
        FROM memory_evidence
        ORDER BY pattern_memory_id, source_memory_id
        """
    ).fetchall() if store._has_memory_evidence else []

    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "memories": [dict(row) for row in rows],
        "evidence_links": [dict(row) for row in evidence_rows],
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
    if version not in {1, 2, BACKUP_VERSION}:
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
        if (
            record["memory_key"] is not None
            and record["memory_type"] != "episodic"
        )
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("Backup contains duplicate memory keys.")

    evidence_links = []
    if version >= 3:
        raw_links = payload.get("evidence_links")
        if not isinstance(raw_links, list):
            raise ValueError("Backup evidence_links must be a JSON array.")
        record_by_id = {record["id"]: record for record in validated}
        seen_links = set()
        links_by_pattern: dict[str, list[dict[str, Any]]] = {}
        for link in raw_links:
            if (
                not isinstance(link, dict)
                or set(link) != {"pattern_memory_id", "source_memory_id"}
            ):
                raise ValueError("Backup contains an invalid evidence link.")
            pattern_id = link["pattern_memory_id"]
            source_id = link["source_memory_id"]
            if (
                not isinstance(pattern_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", pattern_id)
                or not isinstance(source_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", source_id)
                or pattern_id == source_id
            ):
                raise ValueError("Backup contains an invalid evidence memory ID.")
            pair = (pattern_id, source_id)
            if pair in seen_links:
                raise ValueError("Backup contains duplicate evidence links.")
            seen_links.add(pair)
            pattern = record_by_id.get(pattern_id)
            source = record_by_id.get(source_id)
            if (
                pattern is None
                or source is None
                or pattern["memory_type"] != "inferred_pattern"
                or pattern["provenance"] != "inferred"
                or source["provenance"] != "explicit"
                or source["memory_type"] == "inferred_pattern"
                or source["source_message_id"] is None
                or not source["source_conversation_id"]
            ):
                raise ValueError("Backup evidence must connect inferred patterns to explicit source memories.")
            links_by_pattern.setdefault(pattern_id, []).append(source)
            evidence_links.append(pair)

        for pattern_id, sources in links_by_pattern.items():
            message_ids = {source["source_message_id"] for source in sources}
            conversation_ids = {source["source_conversation_id"] for source in sources}
            if len(message_ids) < 3 or len(conversation_ids) < 2:
                raise ValueError(
                    f"Inferred pattern {pattern_id} lacks three independent source messages across two conversations."
                )

        inferred_ids = {
            record["id"] for record in validated
            if record["memory_type"] == "inferred_pattern"
            and record["provenance"] == "inferred"
        }
        if inferred_ids - set(links_by_pattern):
            raise ValueError("Backup contains an inferred pattern without supporting evidence.")

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

                for pattern_id, source_id in evidence_links:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO memory_evidence (
                            pattern_memory_id, source_memory_id, created_at
                        ) VALUES (?, ?, ?)
                        """,
                        (pattern_id, source_id, datetime.now().astimezone().isoformat(timespec="milliseconds")),
                    )
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed: memories.memory_key" in str(error):
            raise ValueError(
                "Memory-key conflict; no data was imported."
            ) from error
        raise ValueError(
            "Database constraint conflict; no data was imported."
        ) from error

    return restored, skipped
