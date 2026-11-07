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
BACKUP_VERSION = 4
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



def _validate_temporal_records(raw: Any, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = {
        "memory_id", "state", "valid_from", "valid_until",
        "recorded_at", "superseded_by", "note",
    }
    states = {"current", "superseded", "corrected", "disputed", "expired"}
    memory_ids = {item["id"] for item in memories}
    if not isinstance(raw, list) or len(raw) > MAX_MEMORIES:
        raise ValueError("Backup temporal_records must be a bounded JSON array.")
    output = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Backup contains an invalid temporal record.")
        memory_id = item["memory_id"]
        replacement = item["superseded_by"]
        if not isinstance(memory_id, str) or memory_id not in memory_ids:
            raise ValueError("Temporal records must reference a memory in the backup.")
        if memory_id in seen:
            raise ValueError("Backup contains duplicate temporal records.")
        seen.add(memory_id)
        state = item["state"]
        if not isinstance(state, str) or state not in states:
            raise ValueError("Backup contains an unsupported temporal state.")
        if state == "superseded" and not replacement:
            raise ValueError("Superseded temporal records require a replacement.")
        if state != "superseded" and replacement is not None:
            raise ValueError("Only superseded temporal records may identify a replacement.")
        if replacement is not None and (
            not isinstance(replacement, str) or replacement not in memory_ids
            or replacement == memory_id
        ):
            raise ValueError("Temporal replacement must reference another backed-up memory.")
        _valid_timestamp(item["valid_from"], "valid_from", optional=True)
        _valid_timestamp(item["valid_until"], "valid_until", optional=True)
        _valid_timestamp(item["recorded_at"], "recorded_at")
        if item["valid_from"] and item["valid_until"]:
            start = datetime.fromisoformat(item["valid_from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(item["valid_until"].replace("Z", "+00:00"))
            if end < start:
                raise ValueError("Temporal validity range is reversed.")
        if not isinstance(item["note"], str) or len(item["note"]) > 2000:
            raise ValueError("Temporal note must be a string of at most 2000 characters.")
        output.append(dict(item))

    by_memory_id = {item["memory_id"]: item for item in output}
    for record in output:
        if record["state"] != "superseded":
            continue
        visited = {record["memory_id"]}
        replacement = record["superseded_by"]
        while replacement in by_memory_id:
            if replacement in visited:
                raise ValueError("Backup contains a circular supersession chain.")
            visited.add(replacement)
            next_record = by_memory_id[replacement]
            if next_record["state"] != "superseded":
                break
            replacement = next_record["superseded_by"]
    return output


def _validate_derivations(raw: Any, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = {"derived_memory_id", "source_memory_id", "state", "created_at"}
    memory_ids = {item["id"] for item in memories}
    if not isinstance(raw, list) or len(raw) > MAX_MEMORIES * 10:
        raise ValueError("Backup derivations must be a bounded JSON array.")
    output = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Backup contains an invalid derivation.")
        derived, source = item["derived_memory_id"], item["source_memory_id"]
        if (
            not isinstance(derived, str) or derived not in memory_ids
            or not isinstance(source, str) or source not in memory_ids
            or derived == source
        ):
            raise ValueError("Derivations must connect distinct backed-up memories.")
        pair = (derived, source)
        if pair in seen:
            raise ValueError("Backup contains duplicate derivations.")
        seen.add(pair)
        state = item["state"]
        if not isinstance(state, str) or state not in {"pending", "accepted", "rejected"}:
            raise ValueError("Backup contains an unsupported derivation state.")
        _valid_timestamp(item["created_at"], "derivation.created_at")
        output.append(dict(item))
    return output


def _validate_commitments(raw: Any, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = {
        "id", "title", "description", "due_at", "recurrence", "state",
        "source_memory_id", "created_at", "updated_at",
    }
    memory_ids = {item["id"] for item in memories}
    if not isinstance(raw, list) or len(raw) > MAX_MEMORIES:
        raise ValueError("Backup commitments must be a bounded JSON array.")
    output = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Backup contains an invalid commitment.")
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id or len(item_id) > 128:
            raise ValueError("Commitment IDs must be non-empty strings.")
        if item_id in seen:
            raise ValueError("Backup contains duplicate commitment IDs.")
        seen.add(item_id)
        if not isinstance(item["title"], str) or not 1 <= len(item["title"].strip()) <= 240:
            raise ValueError("Commitment titles must contain 1 to 240 characters.")
        if not isinstance(item["description"], str) or len(item["description"]) > 4000:
            raise ValueError("Commitment descriptions must be at most 4000 characters.")
        recurrence = item["recurrence"]
        if recurrence is not None and (
            not isinstance(recurrence, str) or len(recurrence) > 200
        ):
            raise ValueError("Commitment recurrence must be at most 200 characters.")
        state = item["state"]
        if not isinstance(state, str) or state not in {"open", "completed", "cancelled"}:
            raise ValueError("Backup contains an unsupported commitment state.")
        source_id = item["source_memory_id"]
        if source_id is not None and (
            not isinstance(source_id, str) or source_id not in memory_ids
        ):
            raise ValueError("Commitment source must reference a backed-up memory.")
        _valid_timestamp(item["due_at"], "commitment.due_at", optional=True)
        _valid_timestamp(item["created_at"], "commitment.created_at")
        _valid_timestamp(item["updated_at"], "commitment.updated_at")
        output.append(dict(item))
    return output

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
        evidence_rows = connection.execute(
            """
            SELECT pattern_memory_id, source_memory_id
            FROM memory_evidence
            ORDER BY pattern_memory_id, source_memory_id
            """
        ).fetchall() if store._has_memory_evidence else []
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        temporal_rows = connection.execute(
            "SELECT memory_id, state, valid_from, valid_until, recorded_at, superseded_by, note "
            "FROM memory_temporal ORDER BY memory_id"
        ).fetchall() if "memory_temporal" in tables else []
        derivation_rows = connection.execute(
            "SELECT derived_memory_id, source_memory_id, state, created_at "
            "FROM memory_derivations ORDER BY derived_memory_id, source_memory_id"
        ).fetchall() if "memory_derivations" in tables else []
        commitment_rows = connection.execute(
            "SELECT id, title, description, due_at, recurrence, state, source_memory_id, "
            "created_at, updated_at FROM memory_commitments ORDER BY created_at, id"
        ).fetchall() if "memory_commitments" in tables else []

    if len(rows) > MAX_MEMORIES:
        raise ValueError(f"Cannot export more than {MAX_MEMORIES} memories.")

    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "memories": [dict(row) for row in rows],
        "evidence_links": [dict(row) for row in evidence_rows],
        "temporal_records": [dict(row) for row in temporal_rows],
        "derivations": [dict(row) for row in derivation_rows],
        "commitments": [dict(row) for row in commitment_rows],
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
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in {1, 2, 3, BACKUP_VERSION}
    ):
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

    temporal_records: list[dict[str, Any]] = []
    derivations: list[dict[str, Any]] = []
    commitments: list[dict[str, Any]] = []
    if version >= 4:
        temporal_records = _validate_temporal_records(payload.get("temporal_records"), validated)
        derivations = _validate_derivations(payload.get("derivations"), validated)
        commitments = _validate_commitments(payload.get("commitments"), validated)

    # Ensure the additive continuity schema exists for every import version.
    # Legacy v3 evidence links are migrated into pending derivation reviews below.
    from v.memory.continuity import ContinuityStore
    ContinuityStore(store.database_path, migrate_legacy_evidence=False)

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

                for record in temporal_records:
                    existing = connection.execute(
                        "SELECT memory_id, state, valid_from, valid_until, recorded_at, superseded_by, note "
                        "FROM memory_temporal WHERE memory_id=?",
                        (record["memory_id"],),
                    ).fetchone()
                    if existing is not None:
                        if dict(existing) == record:
                            continue
                        raise ValueError(
                            f"Temporal memory conflict; no data was imported: {record['memory_id']}"
                        )
                    connection.execute(
                        "INSERT INTO memory_temporal "
                        "(memory_id, state, valid_from, valid_until, recorded_at, superseded_by, note) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        tuple(record[field] for field in (
                            "memory_id", "state", "valid_from", "valid_until",
                            "recorded_at", "superseded_by", "note"
                        )),
                    )

                for record in derivations:
                    existing = connection.execute(
                        "SELECT derived_memory_id, source_memory_id, state, created_at "
                        "FROM memory_derivations WHERE derived_memory_id=? AND source_memory_id=?",
                        (record["derived_memory_id"], record["source_memory_id"]),
                    ).fetchone()
                    if existing is not None:
                        if dict(existing) == record:
                            continue
                        raise ValueError(
                            "Derivation conflict; no data was imported: "
                            f"{record['derived_memory_id']} -> {record['source_memory_id']}"
                        )
                    connection.execute(
                        "INSERT INTO memory_derivations "
                        "(derived_memory_id, source_memory_id, state, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        tuple(record[field] for field in (
                            "derived_memory_id", "source_memory_id", "state", "created_at"
                        )),
                    )

                # Any legacy or incomplete pattern provenance is migrated
                # only after explicit v4 review states have been restored.
                connection.execute(
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

                for record in commitments:
                    existing = connection.execute(
                        "SELECT id, title, description, due_at, recurrence, state, "
                        "source_memory_id, created_at, updated_at "
                        "FROM memory_commitments WHERE id=?",
                        (record["id"],),
                    ).fetchone()
                    if existing is not None:
                        if dict(existing) == record:
                            continue
                        raise ValueError(
                            f"Commitment conflict; no data was imported: {record['id']}"
                        )
                    connection.execute(
                        "INSERT INTO memory_commitments "
                        "(id, title, description, due_at, recurrence, state, source_memory_id, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        tuple(record[field] for field in (
                            "id", "title", "description", "due_at", "recurrence",
                            "state", "source_memory_id", "created_at", "updated_at"
                        )),
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
