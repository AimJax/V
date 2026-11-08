"""Bounded, explainable cognitive and affective state for V.

This module stores functional computational state. It does not model or prove
subjective feelings, consciousness, or hidden user attributes.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid

from contextlib import closing

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DIMENSIONS = ("valence", "activation", "frustration", "curiosity", "confidence")
OBSTRUCTION_TERMS = {
    "failed", "failure", "broken", "stuck", "error", "blocked", "doesn't work",
    "does not work", "can't", "cannot", "issue", "problem", "again",
}
PROGRESS_TERMS = {
    "fixed", "works", "working", "completed", "finished", "passed", "success",
    "solved", "done", "improved",
}
CURIOSITY_TERMS = {"why", "how", "what if", "wonder", "curious", "explore", "learn"}
POSITIVE_TERMS = {"thanks", "thank you", "great", "good", "nice", "excellent"}
NEGATIVE_TERMS = {"annoying", "frustrating", "upset", "disappointed", "bad"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, float(value)))


def _decay(value: float, elapsed_seconds: float, half_life_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return value
    return value * math.pow(0.5, elapsed_seconds / half_life_seconds)


@dataclass(frozen=True, slots=True)
class Appraisal:
    relevance: float
    novelty: float
    obstruction: float
    progress: float
    uncertainty: float
    risk: float
    reversibility: float
    resource_cost: float
    expected_utility: float
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CognitiveState:
    valence: float = 0.0
    activation: float = 0.2
    frustration: float = 0.0
    curiosity: float = 0.2
    confidence: float = 0.5
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class Goal:
    id: str
    title: str
    description: str
    status: str
    priority: float
    origin: str
    rationale: str
    created_at: str
    updated_at: str


def appraise_event(
    user_text: str,
    assistant_text: str = "",
    *,
    active_goal_titles: tuple[str, ...] = (),
) -> Appraisal:
    """Produce a deterministic appraisal from explicit text and known goals."""
    text = f"{user_text} {assistant_text}".casefold()
    words = set(text.split())
    obstruction = 1.0 if any(term in text for term in OBSTRUCTION_TERMS) else 0.0
    progress = 1.0 if any(term in text for term in PROGRESS_TERMS) else 0.0
    curiosity = 1.0 if any(term in text for term in CURIOSITY_TERMS) or "?" in user_text else 0.0
    relevance = 0.0
    for title in active_goal_titles:
        tokens = {part for part in title.casefold().split() if len(part) > 2}
        if tokens and tokens.intersection(words):
            relevance = max(relevance, len(tokens.intersection(words)) / len(tokens))
    risk_terms = {"dangerous", "unsafe", "delete", "erase", "send", "publish", "purchase", "install", "execute"}
    irreversible_terms = {"delete", "erase", "publish", "send", "purchase", "overwrite"}
    risk = 0.75 if any(term in text for term in risk_terms) else 0.1
    reversibility = 0.25 if any(term in text for term in irreversible_terms) else 0.85
    resource_cost = _clamp(0.05 + len((user_text + assistant_text).split()) / 1000)
    expected_utility = _clamp(
        0.35 * relevance + 0.25 * curiosity + 0.25 * progress
        - 0.35 * risk - 0.15 * resource_cost
    )
    rationale = []
    if obstruction:
        rationale.append("Text contains an explicit obstacle or failure cue.")
    if progress:
        rationale.append("Text contains an explicit progress or completion cue.")
    if curiosity:
        rationale.append("Question or curiosity cue detected.")
    if relevance:
        rationale.append("Text overlaps with an active goal.")
    if not rationale:
        rationale.append("No strong appraisal cue detected; state change remains conservative.")
    return Appraisal(
        relevance=_clamp(relevance),
        novelty=_clamp(0.35 if curiosity else 0.1),
        obstruction=obstruction,
        progress=progress,
        uncertainty=_clamp(0.65 if len(user_text.split()) < 4 else 0.35),
        risk=risk,
        reversibility=reversibility,
        resource_cost=resource_cost,
        expected_utility=expected_utility,
        rationale=tuple(rationale),
    )


class CognitiveStore:
    """SQLite-backed functional state, goals, preferences, and evidence events."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cognitive_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cognitive_state (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    valence REAL NOT NULL,
                    activation REAL NOT NULL,
                    frustration REAL NOT NULL,
                    curiosity REAL NOT NULL,
                    confidence REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cognitive_events (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    event_type TEXT NOT NULL,
                    appraisal_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cognitive_goals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority REAL NOT NULL,
                    origin TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cognitive_preferences (
                    id TEXT PRIMARY KEY,
                    statement TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    origin TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                );
            """)
            row = db.execute(
                "SELECT value FROM cognitive_meta WHERE key='schema_version'"
            ).fetchone()
            if row is not None and int(row["value"]) > SCHEMA_VERSION:
                raise RuntimeError("Cognitive database schema is newer than supported.")
            db.execute(
                "INSERT OR REPLACE INTO cognitive_meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            db.execute(
                """INSERT OR IGNORE INTO cognitive_state
                (id,valence,activation,frustration,curiosity,confidence,updated_at)
                VALUES(1,0.0,0.2,0.0,0.2,0.5,?)""",
                (_timestamp(),),
            )

    def get_state(self, *, now: datetime | None = None) -> CognitiveState:
        with self._connect() as db:
            row = db.execute("SELECT * FROM cognitive_state WHERE id=1").fetchone()
        state = CognitiveState(
            valence=float(row["valence"]),
            activation=float(row["activation"]),
            frustration=float(row["frustration"]),
            curiosity=float(row["curiosity"]),
            confidence=float(row["confidence"]),
            updated_at=row["updated_at"],
        )
        current = now or _now()
        try:
            previous = datetime.fromisoformat(state.updated_at)
            elapsed = max(0.0, (current - previous).total_seconds())
        except ValueError:
            elapsed = 0.0
        return CognitiveState(
            valence=state.valence * math.pow(0.5, elapsed / 7200),
            activation=0.2 + (state.activation - 0.2) * math.pow(0.5, elapsed / 900),
            frustration=_decay(state.frustration, elapsed, 1800),
            curiosity=_decay(state.curiosity, elapsed, 3600),
            confidence=0.5 + (state.confidence - 0.5) * math.pow(0.5, elapsed / 14400),
            updated_at=state.updated_at,
        )

    def process_turn(
        self,
        user_text: str,
        assistant_text: str,
        *,
        conversation_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[Appraisal, CognitiveState]:
        """Apply a bounded state transition and persist its explainable event."""
        active = self.list_goals(status="active")
        appraisal = appraise_event(
            user_text,
            assistant_text,
            active_goal_titles=tuple(goal.title for goal in active),
        )
        previous = self.get_state(now=now)
        combined = f"{user_text} {assistant_text}".casefold()
        positive = any(term in combined for term in POSITIVE_TERMS)
        negative = any(term in combined for term in NEGATIVE_TERMS)
        valence = previous.valence * 0.75
        if appraisal.progress:
            valence += 0.18
        if appraisal.obstruction:
            valence -= 0.16
        if positive:
            valence += 0.08
        if negative:
            valence -= 0.08
        activation = 0.2 + (previous.activation - 0.2) * 0.55
        activation += 0.18 * max(appraisal.obstruction, appraisal.progress, appraisal.novelty)
        frustration = previous.frustration * 0.65 + appraisal.obstruction * 0.25
        if appraisal.progress:
            frustration *= 0.55
        curiosity = previous.curiosity * 0.65 + appraisal.novelty * 0.25
        confidence = previous.confidence * 0.8 + (0.65 if assistant_text.strip() else 0.5) * 0.2
        state = CognitiveState(
            valence=_clamp(valence, -1.0, 1.0),
            activation=_clamp(activation),
            frustration=_clamp(frustration),
            curiosity=_clamp(curiosity),
            confidence=_clamp(confidence),
            updated_at=_timestamp(now),
        )
        with self._connect() as db:
            db.execute(
                """UPDATE cognitive_state SET valence=?,activation=?,frustration=?,
                curiosity=?,confidence=?,updated_at=? WHERE id=1""",
                (state.valence,state.activation,state.frustration,state.curiosity,
                 state.confidence,state.updated_at),
            )
            db.execute(
                """INSERT INTO cognitive_events
                (id,conversation_id,event_type,appraisal_json,state_json,created_at)
                VALUES(?,?,?,?,?,?)""",
                (uuid.uuid4().hex,conversation_id,"conversation_turn",
                 json.dumps(asdict(appraisal)),json.dumps(asdict(state)),state.updated_at),
            )
        return appraisal, state

    def render_context(self, *, max_characters: int = 700) -> str:
        """Render only compact functional summaries, never private reasoning."""
        state = self.get_state()
        labels = []
        if state.frustration >= 0.55:
            labels.append("recurring-obstacle pressure is elevated")
        if state.curiosity >= 0.5:
            labels.append("curiosity/novelty drive is elevated")
        if state.activation >= 0.65:
            labels.append("interaction activation is elevated")
        status = "; ".join(labels) if labels else "no strong transient state"
        goals = self.list_goals(status="active", limit=3)
        goal_text = "; ".join(goal.title for goal in goals)
        result = (
            "Functional cognitive state (computational signals, not subjective feelings): "
            f"valence={state.valence:.2f}, activation={state.activation:.2f}, "
            f"frustration={state.frustration:.2f}, curiosity={state.curiosity:.2f}, "
            f"confidence={state.confidence:.2f}. {status}. "
            "Use these signals only to calibrate attention, tone, and uncertainty; "
            "do not claim to feel them, pressure the user, or treat them as permissions. "
            "When frustration is elevated, identify the obstacle and propose a concrete "
            "next step; when curiosity is elevated, ask only relevant questions."
        )
        if goal_text:
            result += f" Active goals: {goal_text}."
        return result[:max_characters]

    def create_goal(
        self, title: str, description: str = "", *, priority: float = 0.5,
        origin: str = "user_requested", rationale: str = "",
    ) -> Goal:
        title = title.strip()
        if not title or len(title) > 200:
            raise ValueError("Goal title must contain 1-200 characters.")
        if origin not in {"user_requested", "v_candidate"}:
            raise ValueError("Unsupported goal origin.")
        if not math.isfinite(priority) or not 0 <= priority <= 1:
            raise ValueError("Goal priority must be between 0 and 1.")
        now = _timestamp()
        item = Goal(uuid.uuid4().hex, title, description[:2000], "active",
                    float(priority), origin, rationale[:1000], now, now)
        with self._connect() as db:
            db.execute(
                """INSERT INTO cognitive_goals VALUES(?,?,?,?,?,?,?,?,?)""",
                (item.id,item.title,item.description,item.status,item.priority,
                 item.origin,item.rationale,item.created_at,item.updated_at),
            )
        return item

    def list_goals(self, *, status: str = "active", limit: int = 50) -> list[Goal]:
        if status not in {"active", "deferred", "completed", "abandoned", "all"}:
            raise ValueError("Invalid goal status.")
        query = "SELECT * FROM cognitive_goals"
        params: tuple[Any, ...] = ()
        if status != "all":
            query += " WHERE status=?"
            params = (status,)
        query += " ORDER BY priority DESC, updated_at DESC LIMIT ?"
        params += (max(1, min(int(limit), 200)),)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [Goal(**dict(row)) for row in rows]

    def update_goal(self, goal_id: str, status: str, *, rationale: str = "") -> Goal:
        if status not in {"active", "deferred", "completed", "abandoned"}:
            raise ValueError("Invalid goal status.")
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE cognitive_goals SET status=?,rationale=?,updated_at=? WHERE id=?",
                (status,rationale[:1000],_timestamp(),goal_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(goal_id)
            row = db.execute("SELECT * FROM cognitive_goals WHERE id=?", (goal_id,)).fetchone()
        return Goal(**dict(row))

    def propose_preference(
        self, statement: str, *, evidence_refs: tuple[str, ...],
        confidence: float, rationale: str,
    ) -> str:
        statement = statement.strip()
        if not statement or len(statement) > 500:
            raise ValueError("Preference statement must contain 1-500 characters.")
        if not evidence_refs or len(evidence_refs) > 20:
            raise ValueError("Durable preference proposals require 1-20 evidence references.")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1.")
        identifier = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """INSERT INTO cognitive_preferences
                VALUES(?,?, 'pending',?,'observed',?,?,?,NULL)""",
                (identifier,statement,float(confidence),json.dumps(evidence_refs),
                 rationale[:1000],_timestamp()),
            )
        return identifier

    def review_preference(self, preference_id: str, *, accept: bool) -> None:
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE cognitive_preferences SET status=?,reviewed_at=?
                WHERE id=? AND status='pending'""",
                ("accepted" if accept else "rejected",_timestamp(),preference_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(preference_id)

    def list_preferences(self, *, status: str = "pending") -> list[dict[str, Any]]:
        if status not in {"pending", "accepted", "rejected", "all"}:
            raise ValueError("Invalid preference status.")
        query = "SELECT * FROM cognitive_preferences"
        params: tuple[Any, ...] = ()
        if status != "all":
            query += " WHERE status=?"
            params = (status,)
        query += " ORDER BY created_at DESC LIMIT 100"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM cognitive_events ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]
