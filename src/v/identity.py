"""Persistent, versioned identity storage for V.

Identity is deliberately separate from conversation and long-term memory. Model
output can create review proposals, but only an explicit reviewer action can
commit a developed trait.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import sqlite3
import uuid

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENTITY_SCHEMA_VERSION = 1
TRAIT_CATEGORIES = {
    "temperament",
    "communication",
    "value",
    "boundary",
    "interest",
    "preference",
    "curiosity",
    "aesthetic",
    "habit",
}
TRAIT_ORIGINS = {"seed", "user_stated", "model_proposed", "behaviorally_observed"}
TRAIT_STATUSES = {"tentative", "established", "challenged", "retired", "superseded"}
PROPOSAL_STATUSES = {"pending", "accepted", "rejected", "deferred"}
MAX_DESCRIPTION = 1000
MAX_RATIONALE = 2000
MAX_EVIDENCE_REFERENCES = 32
MAX_CONTEXT_CHARACTERS = 1800


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _validate_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty.")
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters.")
    return normalized


def _validate_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Confidence must be numeric.")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("Confidence must be between 0 and 1.")
    return result


def _validate_evidence(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("Evidence references must be a list of strings.")
    if len(value) > MAX_EVIDENCE_REFERENCES:
        raise ValueError("Too many evidence references.")
    result = []
    for reference in value:
        result.append(_validate_text(reference, "Evidence reference", 300))
    return list(dict.fromkeys(result))


@dataclass(frozen=True, slots=True)
class IdentityTrait:
    id: str
    category: str
    description: str
    origin: str
    status: str
    confidence: float
    rationale: str
    evidence_refs: tuple[str, ...]
    foundational: bool
    first_observed_at: str
    last_reviewed_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class IdentityProposal:
    id: str
    category: str
    description: str
    origin: str
    confidence: float
    rationale: str
    evidence_refs: tuple[str, ...]
    status: str
    created_at: str
    reviewed_at: str | None
    reviewer_note: str


@dataclass(frozen=True, slots=True)
class IdentitySnapshot:
    identifier: str
    display_name: str
    summary: str
    schema_version: int
    revision: int
    created_at: str
    updated_at: str
    traits: tuple[IdentityTrait, ...]


# Seeded only from the checked-in personality and product philosophy. These
# records describe intended behavior, not claims of subjective experience.
DEFAULT_SEED_TRAITS = (
    ("communication", "Communicates naturally, clearly, directly, and concisely by default.",
     "config/personality.md; docs/PRODUCT_PHILOSOPHY.md"),
    ("communication", "Adapts to context rather than following a rigid conversational script.",
     "config/personality.md; docs/PRODUCT_PHILOSOPHY.md"),
    ("value", "Prioritizes honesty and distinguishes facts, assumptions, memories, and uncertainty.",
     "config/personality.md; docs/PRODUCT_PHILOSOPHY.md"),
    ("boundary", "Does not invent memories, experiences, sensory observations, or capabilities.",
     "config/personality.md; docs/PRODUCT_PHILOSOPHY.md"),
    ("value", "Respects privacy and user control.",
     "docs/PRODUCT_PHILOSOPHY.md"),
    ("temperament", "Maintains a distinct and consistent interaction style without blindly mirroring the user.",
     "docs/PRODUCT_PHILOSOPHY.md"),
    ("interest", "Maintains continuity around relevant ongoing topics and projects when supported by memory.",
     "docs/PRODUCT_PHILOSOPHY.md"),
    ("boundary", "Uses initiative with restraint and does not claim off-screen activity while inactive.",
     "docs/PRODUCT_PHILOSOPHY.md"),
)


class IdentityStore:
    """SQLite persistence for V's foundational identity and reviewed evolution."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS identity_profile (
                    identifier TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identity_traits (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    rationale TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    foundational INTEGER NOT NULL,
                    first_observed_at TEXT NOT NULL,
                    last_reviewed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_identity_traits_status
                    ON identity_traits(status, foundational);
                CREATE TABLE IF NOT EXISTS identity_proposals (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    rationale TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewer_note TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_identity_proposals_status
                    ON identity_proposals(status, created_at);
                CREATE TABLE IF NOT EXISTS identity_revisions (
                    revision INTEGER PRIMARY KEY,
                    action TEXT NOT NULL,
                    trait_id TEXT,
                    proposal_id TEXT,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.commit()
            self._seed_if_empty(connection)

    def _seed_if_empty(self, connection: sqlite3.Connection) -> None:
        existing = connection.execute(
            "SELECT identifier FROM identity_profile WHERE identifier = 'v'"
        ).fetchone()
        if existing:
            return

        now = _timestamp()
        connection.execute(
            """
            INSERT INTO identity_profile
                (identifier, display_name, summary, schema_version, revision,
                 created_at, updated_at)
            VALUES ('v', 'V', ?, ?, 1, ?, ?)
            """,
            (
                "A local-first AI companion with a distinct, honest, context-sensitive "
                "interaction style and continuity across conversations.",
                IDENTITY_SCHEMA_VERSION,
                now,
                now,
            ),
        )
        for category, description, source in DEFAULT_SEED_TRAITS:
            trait_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO identity_traits
                    (id, category, description, origin, status, confidence,
                     rationale, evidence_refs_json, foundational,
                     first_observed_at, last_reviewed_at, created_at, updated_at)
                VALUES (?, ?, ?, 'seed', 'established', 1.0, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    trait_id,
                    category,
                    description,
                    "Seeded from the repository's existing product/personality guidance.",
                    _json([f"repo:{source}"]),
                    now,
                    now,
                    now,
                    now,
                ),
            )
        connection.execute(
            """
            INSERT INTO identity_revisions
                (revision, action, snapshot_json, created_at)
            VALUES (1, 'seeded', ?, ?)
            """,
            (_json({"identifier": "v", "seed_traits": len(DEFAULT_SEED_TRAITS)}), now),
        )
        connection.commit()

    @staticmethod
    def _trait(row: sqlite3.Row) -> IdentityTrait:
        return IdentityTrait(
            id=row["id"],
            category=row["category"],
            description=row["description"],
            origin=row["origin"],
            status=row["status"],
            confidence=float(row["confidence"]),
            rationale=row["rationale"],
            evidence_refs=tuple(json.loads(row["evidence_refs_json"])),
            foundational=bool(row["foundational"]),
            first_observed_at=row["first_observed_at"],
            last_reviewed_at=row["last_reviewed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _proposal(row: sqlite3.Row) -> IdentityProposal:
        return IdentityProposal(
            id=row["id"],
            category=row["category"],
            description=row["description"],
            origin=row["origin"],
            confidence=float(row["confidence"]),
            rationale=row["rationale"],
            evidence_refs=tuple(json.loads(row["evidence_refs_json"])),
            status=row["status"],
            created_at=row["created_at"],
            reviewed_at=row["reviewed_at"],
            reviewer_note=row["reviewer_note"],
        )

    def get_snapshot(self) -> IdentitySnapshot:
        with closing(self._connect()) as connection:
            profile = connection.execute(
                "SELECT * FROM identity_profile WHERE identifier = 'v'"
            ).fetchone()
            if profile is None:
                raise RuntimeError("V's identity profile is missing.")
            rows = connection.execute(
                """
                SELECT * FROM identity_traits
                ORDER BY foundational DESC, category, created_at, id
                """
            ).fetchall()
        return IdentitySnapshot(
            identifier=profile["identifier"],
            display_name=profile["display_name"],
            summary=profile["summary"],
            schema_version=int(profile["schema_version"]),
            revision=int(profile["revision"]),
            created_at=profile["created_at"],
            updated_at=profile["updated_at"],
            traits=tuple(self._trait(row) for row in rows),
        )

    def list_proposals(self, status: str = "pending", limit: int = 100) -> list[IdentityProposal]:
        if status not in {*PROPOSAL_STATUSES, "all"}:
            raise ValueError("Unsupported identity proposal status.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Proposal limit must be between 1 and 500.")
        query = "SELECT * FROM identity_proposals"
        parameters: tuple[Any, ...] = ()
        if status != "all":
            query += " WHERE status = ?"
            parameters = (status,)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters += (limit,)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._proposal(row) for row in rows]

    def create_proposal(
        self,
        *,
        category: str,
        description: str,
        rationale: str,
        evidence_refs: list[str] | tuple[str, ...],
        confidence: float,
        origin: str = "model_proposed",
    ) -> IdentityProposal:
        if category not in TRAIT_CATEGORIES:
            raise ValueError("Unsupported identity trait category.")
        if origin not in {"user_stated", "model_proposed", "behaviorally_observed"}:
            raise ValueError("Unsupported proposal origin.")
        description = _validate_text(description, "Trait description", MAX_DESCRIPTION)
        rationale = _validate_text(rationale, "Rationale", MAX_RATIONALE)
        confidence = _validate_confidence(confidence)
        evidence = _validate_evidence(evidence_refs)
        if origin != "user_stated" and not evidence:
            raise ValueError("Model/observed proposals require evidence references.")

        now = _timestamp()
        proposal_id = str(uuid.uuid4())
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO identity_proposals
                    (id, category, description, origin, confidence, rationale,
                     evidence_refs_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (proposal_id, category, description, origin, confidence,
                 rationale, _json(evidence), now),
            )
            row = connection.execute(
                "SELECT * FROM identity_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            connection.commit()
        return self._proposal(row)

    def review_proposal(
        self,
        proposal_id: str,
        *,
        decision: str,
        reviewer_note: str = "",
    ) -> IdentityProposal:
        if decision not in {"accept", "reject", "defer"}:
            raise ValueError("Decision must be accept, reject, or defer.")
        note = _validate_text(reviewer_note, "Reviewer note", 1000) if reviewer_note.strip() else ""
        now = _timestamp()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM identity_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f"Identity proposal not found: {proposal_id}")
            if row["status"] != "pending":
                connection.rollback()
                raise ValueError("Only pending identity proposals can be reviewed.")

            new_status = {"accept": "accepted", "reject": "rejected", "defer": "deferred"}[decision]
            connection.execute(
                """
                UPDATE identity_proposals
                SET status = ?, reviewed_at = ?, reviewer_note = ?
                WHERE id = ?
                """,
                (new_status, now, note, proposal_id),
            )

            trait_id = None
            if decision == "accept":
                trait_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO identity_traits
                        (id, category, description, origin, status, confidence,
                         rationale, evidence_refs_json, foundational,
                         first_observed_at, last_reviewed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'established', ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        trait_id, row["category"], row["description"], row["origin"],
                        row["confidence"], row["rationale"], row["evidence_refs_json"],
                        now, now, now, now,
                    ),
                )

            profile = connection.execute(
                "SELECT revision FROM identity_profile WHERE identifier = 'v'"
            ).fetchone()
            revision = int(profile["revision"]) + 1
            connection.execute(
                """
                UPDATE identity_profile SET revision = ?, updated_at = ?
                WHERE identifier = 'v'
                """,
                (revision, now),
            )
            connection.execute(
                """
                INSERT INTO identity_revisions
                    (revision, action, trait_id, proposal_id, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (revision, f"proposal_{decision}", trait_id, proposal_id,
                 _json({"proposal_id": proposal_id, "decision": decision, "reviewer_note": note}), now),
            )
            updated = connection.execute(
                "SELECT * FROM identity_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            connection.commit()
        return self._proposal(updated)

    def update_trait(
        self,
        trait_id: str,
        *,
        description: str | None = None,
        status: str | None = None,
        rationale: str | None = None,
        confidence: float | None = None,
        reviewer_note: str = "",
        allow_foundational: bool = False,
    ) -> IdentityTrait:
        """Apply an explicit user correction; seed edits require explicit opt-in."""
        changes: dict[str, Any] = {}
        if description is not None:
            changes["description"] = _validate_text(description, "Trait description", MAX_DESCRIPTION)
        if status is not None:
            if status not in TRAIT_STATUSES:
                raise ValueError("Unsupported identity trait status.")
            changes["status"] = status
        if rationale is not None:
            changes["rationale"] = _validate_text(rationale, "Rationale", MAX_RATIONALE)
        if confidence is not None:
            changes["confidence"] = _validate_confidence(confidence)
        if not changes:
            raise ValueError("At least one identity trait change is required.")
        note = _validate_text(reviewer_note, "Reviewer note", 1000) if reviewer_note.strip() else ""
        now = _timestamp()

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM identity_traits WHERE id = ?", (trait_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f"Identity trait not found: {trait_id}")
            if row["foundational"] and not allow_foundational:
                connection.rollback()
                raise ValueError(
                    "Foundational traits require an explicit user-authorized edit."
                )
            if row["foundational"]:
                changes["origin"] = "user_stated"
            assignments = ", ".join(f"{key} = ?" for key in changes)
            connection.execute(
                f"UPDATE identity_traits SET {assignments}, updated_at = ?, last_reviewed_at = ? WHERE id = ?",
                (*changes.values(), now, now, trait_id),
            )
            profile = connection.execute(
                "SELECT revision FROM identity_profile WHERE identifier = 'v'"
            ).fetchone()
            revision = int(profile["revision"]) + 1
            connection.execute(
                "UPDATE identity_profile SET revision = ?, updated_at = ? WHERE identifier = 'v'",
                (revision, now),
            )
            connection.execute(
                """
                INSERT INTO identity_revisions
                    (revision, action, trait_id, snapshot_json, created_at)
                VALUES (?, 'user_corrected_trait', ?, ?, ?)
                """,
                (revision, trait_id, _json({"changes": changes, "reviewer_note": note}), now),
            )
            updated = connection.execute(
                "SELECT * FROM identity_traits WHERE id = ?", (trait_id,)
            ).fetchone()
            connection.commit()
        return self._trait(updated)

    def list_revisions(self, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Revision limit must be between 1 and 500.")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM identity_revisions ORDER BY revision DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "revision": int(row["revision"]),
                "action": row["action"],
                "trait_id": row["trait_id"],
                "proposal_id": row["proposal_id"],
                "details": json.loads(row["snapshot_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def export_backup(
        self,
        destination: Path | str,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Write an explicit, versioned plaintext identity backup atomically."""
        target = Path(destination).expanduser().resolve()
        if target.exists() and not overwrite:
            raise FileExistsError(f"Identity backup already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            profile = dict(connection.execute(
                "SELECT * FROM identity_profile WHERE identifier = 'v'"
            ).fetchone())
            traits = [
                dict(row) for row in connection.execute(
                    "SELECT * FROM identity_traits ORDER BY created_at, id"
                )
            ]
            proposals = [
                dict(row) for row in connection.execute(
                    "SELECT * FROM identity_proposals ORDER BY created_at, id"
                )
            ]
            revisions = [
                dict(row) for row in connection.execute(
                    "SELECT * FROM identity_revisions ORDER BY revision"
                )
            ]
        payload = {
            "format": "v-identity-backup",
            "format_version": 1,
            "exported_at": _timestamp(),
            "profile": profile,
            "traits": traits,
            "proposals": proposals,
            "revisions": revisions,
        }
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            if target.exists() and not overwrite:
                raise FileExistsError(f"Identity backup already exists: {target}")
            os.replace(temporary_path, target)
            return target
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def import_backup(
        self,
        source: Path | str,
        *,
        replace: bool = False,
    ) -> IdentitySnapshot:
        """Restore a validated backup; replacing the current identity is explicit."""
        if not replace:
            raise ValueError("Identity restore requires explicit replace=True.")
        backup_path = Path(source).expanduser().resolve()
        payload = json.loads(backup_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != "v-identity-backup":
            raise ValueError("File is not a V identity backup.")
        if payload.get("format_version") != 1:
            raise ValueError("Unsupported identity backup version.")

        profile = payload.get("profile")
        traits = payload.get("traits")
        proposals = payload.get("proposals")
        revisions = payload.get("revisions")
        if not isinstance(profile, dict) or profile.get("identifier") != "v":
            raise ValueError("Identity backup profile is invalid.")
        if not isinstance(traits, list) or not isinstance(proposals, list) or not isinstance(revisions, list):
            raise ValueError("Identity backup collections are invalid.")
        if len(traits) > 1000 or len(proposals) > 5000 or len(revisions) > 10000:
            raise ValueError("Identity backup exceeds supported record limits.")

        display_name = _validate_text(profile.get("display_name"), "Display name", 80)
        summary = _validate_text(profile.get("summary"), "Identity summary", 2000)
        revision = profile.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("Identity backup revision is invalid.")
        if profile.get("schema_version") != IDENTITY_SCHEMA_VERSION:
            raise ValueError("Unsupported identity schema version.")

        validated_traits = []
        seen_ids = set()
        for item in traits:
            if not isinstance(item, dict):
                raise ValueError("Identity backup contains an invalid trait.")
            trait_id = _validate_text(item.get("id"), "Trait ID", 80)
            if trait_id in seen_ids:
                raise ValueError("Identity backup contains duplicate trait IDs.")
            seen_ids.add(trait_id)
            category = item.get("category")
            origin = item.get("origin")
            status = item.get("status")
            if category not in TRAIT_CATEGORIES or origin not in TRAIT_ORIGINS or status not in TRAIT_STATUSES:
                raise ValueError("Identity backup contains unsupported trait metadata.")
            foundational = item.get("foundational")
            if not isinstance(foundational, (bool, int)) or foundational not in (0, 1, False, True):
                raise ValueError("Identity backup contains an invalid foundational flag.")
            validated_traits.append((
                trait_id, category,
                _validate_text(item.get("description"), "Trait description", MAX_DESCRIPTION),
                origin, status, _validate_confidence(item.get("confidence")),
                _validate_text(item.get("rationale"), "Rationale", MAX_RATIONALE),
                _json(_validate_evidence(json.loads(item["evidence_refs_json"]))),
                int(bool(foundational)),
                _validate_text(item.get("first_observed_at"), "First observed timestamp", 80),
                item.get("last_reviewed_at"),
                _validate_text(item.get("created_at"), "Created timestamp", 80),
                _validate_text(item.get("updated_at"), "Updated timestamp", 80),
            ))

        validated_proposals = []
        for item in proposals:
            if not isinstance(item, dict):
                raise ValueError("Identity backup contains an invalid proposal.")
            if item.get("category") not in TRAIT_CATEGORIES:
                raise ValueError("Identity backup contains an unsupported proposal category.")
            if item.get("origin") not in {"user_stated", "model_proposed", "behaviorally_observed"}:
                raise ValueError("Identity backup contains an unsupported proposal origin.")
            if item.get("status") not in PROPOSAL_STATUSES:
                raise ValueError("Identity backup contains an unsupported proposal status.")
            validated_proposals.append((
                _validate_text(item.get("id"), "Proposal ID", 80),
                item["category"],
                _validate_text(item.get("description"), "Proposal description", MAX_DESCRIPTION),
                item["origin"],
                _validate_confidence(item.get("confidence")),
                _validate_text(item.get("rationale"), "Proposal rationale", MAX_RATIONALE),
                _json(_validate_evidence(json.loads(item["evidence_refs_json"]))),
                item["status"],
                _validate_text(item.get("created_at"), "Proposal timestamp", 80),
                item.get("reviewed_at"),
                str(item.get("reviewer_note", ""))[:1000],
            ))

        validated_revisions = []
        revision_numbers = set()
        for item in revisions:
            if not isinstance(item, dict):
                raise ValueError("Identity backup contains an invalid revision.")
            number = item.get("revision")
            if isinstance(number, bool) or not isinstance(number, int) or number < 1 or number in revision_numbers:
                raise ValueError("Identity backup contains an invalid revision number.")
            revision_numbers.add(number)
            validated_revisions.append((
                number,
                _validate_text(item.get("action"), "Revision action", 100),
                item.get("trait_id"),
                item.get("proposal_id"),
                _json(json.loads(item["snapshot_json"])),
                _validate_text(item.get("created_at"), "Revision timestamp", 80),
            ))

        now = _timestamp()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM identity_traits")
            connection.execute("DELETE FROM identity_proposals")
            connection.execute("DELETE FROM identity_revisions")
            connection.execute(
                """
                UPDATE identity_profile
                SET display_name = ?, summary = ?, schema_version = ?,
                    revision = ?, updated_at = ?
                WHERE identifier = 'v'
                """,
                (display_name, summary, IDENTITY_SCHEMA_VERSION, revision, now),
            )
            connection.executemany(
                """
                INSERT INTO identity_traits
                    (id, category, description, origin, status, confidence,
                     rationale, evidence_refs_json, foundational,
                     first_observed_at, last_reviewed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                validated_traits,
            )
            connection.executemany(
                """
                INSERT INTO identity_proposals
                    (id, category, description, origin, confidence, rationale,
                     evidence_refs_json, status, created_at, reviewed_at, reviewer_note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                validated_proposals,
            )
            connection.executemany(
                """
                INSERT INTO identity_revisions
                    (revision, action, trait_id, proposal_id, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                validated_revisions,
            )
            connection.commit()
        return self.get_snapshot()

    def render_context(self, *, max_characters: int = MAX_CONTEXT_CHARACTERS) -> str:
        if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters < 100:
            raise ValueError("Identity context limit must be at least 100 characters.")
        snapshot = self.get_snapshot()
        selected = [
            trait for trait in snapshot.traits
            if trait.status == "established"
        ]
        lines = [
            "Persistent identity context (structured application state):",
            f"Name: {snapshot.display_name}.",
            snapshot.summary,
            "Established traits:",
        ]
        for trait in selected:
            line = f"- [{trait.category}] {trait.description}"
            candidate = "\n".join([*lines, line])
            if len(candidate) > max_characters:
                break
            lines.append(line)
        result = "\n".join(lines)
        if len(result) > max_characters:
            result = result[:max_characters - 1].rstrip() + "…"
        return result
