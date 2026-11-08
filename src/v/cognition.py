"""Bounded, explainable cognitive and affective state for V.

This module stores functional computational state. It does not model or prove
subjective feelings, consciousness, or hidden user attributes.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid

from contextlib import closing

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
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
    user_signal = user_text.casefold()
    words = set(re.findall(r"[\w]+", text, flags=re.UNICODE))
    obstruction = 1.0 if any(term in user_signal for term in OBSTRUCTION_TERMS) else 0.0
    progress = 1.0 if any(term in user_signal for term in PROGRESS_TERMS) else 0.0
    curiosity = 1.0 if any(term in user_signal for term in CURIOSITY_TERMS) or "?" in user_text else 0.0
    relevance = 0.0
    for title in active_goal_titles:
        tokens = {part for part in title.casefold().split() if len(part) > 2}
        if tokens and tokens.intersection(words):
            relevance = max(relevance, len(tokens.intersection(words)) / len(tokens))
    action_pattern = re.compile(
        r"\b(?:please\s+)?(?:delete|erase|publish|send|purchase|buy|install|execute|overwrite)"
        r"\s+(?:the|my|this|that|all|a|an)?\s*"
        r"(?:file|files|data|message|email|post|software|package|command|record|account)\b"
    )
    irreversible_pattern = re.compile(
        r"\b(?:delete|erase|publish|purchase|buy|overwrite)\s+"
        r"(?:the|my|this|that|all|a|an)?\s*"
        r"(?:file|files|data|message|email|post|software|package|record|account)\b"
    )
    risk = 0.8 if action_pattern.search(user_signal) else (
        0.55 if any(term in user_signal for term in ("dangerous", "unsafe")) else 0.05
    )
    reversibility = 0.2 if irreversible_pattern.search(user_signal) else 0.85
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
        uncertainty=_clamp(
            0.75 if any(marker in user_signal for marker in (
                "maybe", "not sure", "uncertain", "i guess", "probably",
                "might be", "could be",
            )) else 0.55 if len(user_text.split()) < 4 else 0.25
        ),
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
                CREATE TABLE IF NOT EXISTS cognitive_memory_salience (
                    memory_id TEXT PRIMARY KEY,
                    score REAL NOT NULL CHECK(score >= 0 AND score <= 1),
                    hits INTEGER NOT NULL DEFAULT 1,
                    rationale TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cognitive_goal_proposals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    priority REAL NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
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
        with closing(self._connect()) as connection, connection as db:
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
        salient_memory_ids: tuple[str, ...] = (),
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
        user_signal = user_text.casefold()
        positive = any(term in user_signal for term in POSITIVE_TERMS)
        negative = any(term in user_signal for term in NEGATIVE_TERMS)
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
        recent_events = self.recent_events(limit=12)
        recent_obstacles = sum(
            1 for event in recent_events
            if event["event_type"] == "conversation_turn"
            and bool(json.loads(event["appraisal_json"]).get("obstruction"))
        )
        repeated_pressure = min(0.12, max(0, recent_obstacles - 1) * 0.03)
        frustration = (
            previous.frustration * 0.65
            + appraisal.obstruction * (0.20 + repeated_pressure)
        )
        if appraisal.progress:
            frustration *= 0.55
        curiosity = previous.curiosity * 0.65 + appraisal.novelty * 0.25
        assistant_uncertainty = any(
            marker in assistant_text.casefold()
            for marker in ("i am not sure", "i'm not sure", "uncertain", "i cannot verify", "i don't know")
        )
        confidence_target = (
            0.42 if assistant_uncertainty else
            0.58 if appraisal.uncertainty >= 0.6 else 0.62
        )
        confidence = previous.confidence * 0.8 + confidence_target * 0.2
        state = CognitiveState(
            valence=_clamp(valence, -1.0, 1.0),
            activation=_clamp(activation),
            frustration=_clamp(frustration),
            curiosity=_clamp(curiosity),
            confidence=_clamp(confidence),
            updated_at=_timestamp(now),
        )
        with closing(self._connect()) as connection, connection as db:
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
        if salient_memory_ids:
            self.record_memory_salience(salient_memory_ids, appraisal, now=now)
        return appraisal, state

    def render_context(self, *, max_characters: int = 700, query: str = "") -> str:
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
        ranked = (
            self.rank_goals(query, limit=10)
            if query.strip()
            else [(goal, 0.0) for goal in self.list_goals(status="active", limit=3)]
        )
        selected_goals = (
            [goal for goal, score in ranked if score >= 0.5][:3]
            if query.strip()
            else [goal for goal, _score in ranked[:3]]
        )
        goal_text = "; ".join(goal.title for goal in selected_goals)
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
        accepted_preferences = self.list_preferences(status="accepted")[:5]
        if accepted_preferences:
            preference_text = "; ".join(
                f"{item['statement']} (confidence {item['confidence']:.2f})"
                for item in accepted_preferences
            )
            result += f" User-reviewed preferences: {preference_text}."
        return result[:max_characters]

    def propose_goal(
        self, title: str, *, description: str = "", priority: float = 0.5,
        evidence_refs: tuple[str, ...], rationale: str,
    ) -> str:
        """Create a pending, evidence-backed V-originated goal candidate."""
        title = title.strip()
        refs = tuple(dict.fromkeys(
            ref.strip() for ref in evidence_refs
            if isinstance(ref, str) and ref.strip()
        ))
        if not title or len(title) > 200:
            raise ValueError("Goal proposal title must contain 1-200 characters.")
        if len(refs) < 2 or len(refs) > 20:
            raise ValueError("Goal proposals require 2-20 distinct evidence references.")
        if not math.isfinite(priority) or not 0 <= priority <= 1:
            raise ValueError("Goal priority must be between 0 and 1.")
        identifier = uuid.uuid4().hex
        with closing(self._connect()) as connection, connection as db:
            db.execute(
                """INSERT INTO cognitive_goal_proposals
                VALUES(?,?,?,?,?,?,'pending',?,NULL)""",
                (identifier, title, description[:2000], float(priority),
                 json.dumps(refs), rationale[:1000], _timestamp()),
            )
        return identifier

    def list_goal_proposals(self, *, status: str = "pending") -> list[dict[str, Any]]:
        if status not in {"pending", "accepted", "rejected", "all"}:
            raise ValueError("Invalid goal proposal status.")
        query = "SELECT * FROM cognitive_goal_proposals"
        params: tuple[Any, ...] = ()
        if status != "all":
            query += " WHERE status=?"
            params = (status,)
        query += " ORDER BY created_at DESC LIMIT 100"
        with closing(self._connect()) as connection, connection as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def review_goal_proposal(self, proposal_id: str, *, accept: bool) -> Goal | None:
        """Review a candidate; accepted candidates become plans, never actions."""
        with closing(self._connect()) as connection, connection as db:
            row = db.execute(
                "SELECT * FROM cognitive_goal_proposals WHERE id=? AND status='pending'",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            status = "accepted" if accept else "rejected"
            goal = None
            if accept:
                now = _timestamp()
                goal = Goal(
                    uuid.uuid4().hex, row["title"], row["description"], "active",
                    float(row["priority"]), "v_candidate",
                    f"User accepted candidate. {row['rationale']}"[:1000],
                    now, now,
                )
                db.execute(
                    "INSERT INTO cognitive_goals VALUES(?,?,?,?,?,?,?,?,?)",
                    (goal.id, goal.title, goal.description, goal.status, goal.priority,
                     goal.origin, goal.rationale, goal.created_at, goal.updated_at),
                )
            db.execute(
                "UPDATE cognitive_goal_proposals SET status=?,reviewed_at=? WHERE id=?",
                (status, _timestamp(), proposal_id),
            )
        return goal

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
        with closing(self._connect()) as connection, connection as db:
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
        with closing(self._connect()) as connection, connection as db:
            rows = db.execute(query, params).fetchall()
        return [Goal(**dict(row)) for row in rows]

    def update_goal(self, goal_id: str, status: str, *, rationale: str = "") -> Goal:
        if status not in {"active", "deferred", "completed", "abandoned"}:
            raise ValueError("Invalid goal status.")
        with closing(self._connect()) as connection, connection as db:
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
        unique_evidence = tuple(dict.fromkeys(
            ref.strip() for ref in evidence_refs if isinstance(ref, str) and ref.strip()
        ))
        if len(unique_evidence) < 2 or len(unique_evidence) > 20:
            raise ValueError("Durable preference proposals require 2-20 distinct evidence references.")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1.")
        identifier = uuid.uuid4().hex
        with closing(self._connect()) as connection, connection as db:
            db.execute(
                """INSERT INTO cognitive_preferences
                VALUES(?,?, 'pending',?,'observed',?,?,?,NULL)""",
                (identifier,statement,float(confidence),json.dumps(unique_evidence),
                 rationale[:1000],_timestamp()),
            )
        return identifier

    def review_preference(self, preference_id: str, *, accept: bool) -> None:
        with closing(self._connect()) as connection, connection as db:
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
        with closing(self._connect()) as connection, connection as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def record_memory_salience(
        self, memory_ids: tuple[str, ...] | list[str], appraisal: Appraisal,
        *, now: datetime | None = None,
    ) -> None:
        """Persist bounded attention salience without changing source memories."""
        current = _timestamp(now)
        increment = _clamp(
            0.04 + 0.10 * appraisal.relevance
            + 0.08 * appraisal.novelty + 0.06 * appraisal.progress
        )
        rationale = "; ".join(appraisal.rationale)[:500]
        unique_ids = tuple(dict.fromkeys(
            item.strip() for item in memory_ids if isinstance(item, str) and item.strip()
        ))[:50]
        if not unique_ids:
            return
        with closing(self._connect()) as connection, connection as db:
            for memory_id in unique_ids:
                row = db.execute(
                    "SELECT score,hits,updated_at FROM cognitive_memory_salience WHERE memory_id=?",
                    (memory_id,),
                ).fetchone()
                previous = 0.0
                hits = 0
                if row is not None:
                    try:
                        elapsed = max(
                            0.0,
                            (datetime.fromisoformat(current)
                             - datetime.fromisoformat(row["updated_at"])).total_seconds(),
                        )
                    except ValueError:
                        elapsed = 0.0
                    previous = _decay(float(row["score"]), elapsed, 21600)
                    hits = int(row["hits"])
                db.execute(
                    """INSERT INTO cognitive_memory_salience
                    (memory_id,score,hits,rationale,updated_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                    score=excluded.score,hits=excluded.hits,
                    rationale=excluded.rationale,updated_at=excluded.updated_at""",
                    (memory_id, _clamp(previous + increment), hits + 1, rationale, current),
                )

    def prioritize_memories(self, memories: list[Any], *, now: datetime | None = None) -> list[Any]:
        """Apply a small salience tie-break while preserving retrieval relevance."""
        if len(memories) < 2:
            return list(memories)
        ids = [item.id for item in memories]
        placeholders = ",".join("?" for _ in ids)
        with closing(self._connect()) as connection, connection as db:
            rows = db.execute(
                f"SELECT memory_id,score,updated_at FROM cognitive_memory_salience "
                f"WHERE memory_id IN ({placeholders})",
                ids,
            ).fetchall()
        scores = {}
        current = now or _now()
        for row in rows:
            try:
                elapsed = max(
                    0.0,
                    (current - datetime.fromisoformat(row["updated_at"])).total_seconds(),
                )
            except ValueError:
                elapsed = 0.0
            scores[row["memory_id"]] = _decay(float(row["score"]), elapsed, 21600)
        indexed = list(enumerate(memories))
        indexed.sort(
            key=lambda pair: (
                pair[0] - (1.1 if scores.get(pair[1].id, 0.0) >= 0.18 else 0.0),
                pair[0],
            )
        )
        return [item for _index, item in indexed]

    def memory_salience(self, memory_id: str, *, now: datetime | None = None) -> float:
        with closing(self._connect()) as connection, connection as db:
            row = db.execute(
                "SELECT score,updated_at FROM cognitive_memory_salience WHERE memory_id=?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return 0.0
        try:
            elapsed = max(0.0, ((now or _now()) - datetime.fromisoformat(row["updated_at"])).total_seconds())
        except ValueError:
            elapsed = 0.0
        return _clamp(_decay(float(row["score"]), elapsed, 21600))

    def rank_goals(self, context: str, *, limit: int = 5) -> list[tuple[Goal, float]]:
        """Rank existing goals for attention; ranking never executes a goal."""
        terms = {word for word in context.casefold().split() if len(word) >= 2}
        ranked = []
        for goal in self.list_goals(status="active", limit=200):
            goal_terms = {
                word for word in re.findall(r"[\w]+", goal.title.casefold())
                if len(word) >= 2
            }
            relevance = (
                len(terms.intersection(goal_terms)) / len(goal_terms)
                if goal_terms else 0.0
            )
            appraisal = appraise_event(
                context, active_goal_titles=(goal.title,)
            )
            resource_fit = 1.0 - appraisal.resource_cost
            score = _clamp(
                0.45 * relevance + 0.30 * goal.priority
                + 0.15 * appraisal.expected_utility + 0.10 * resource_fit
            )
            ranked.append((goal, score))
        ranked.sort(key=lambda item: (item[1], item[0].updated_at), reverse=True)
        return ranked[:max(1, min(int(limit), 20))]

    def reflect(self, *, now: datetime | None = None,
                minimum_interval_seconds: int = 900) -> str | None:
        """Create a short, globally rate-limited outcome summary from recorded events."""
        current = now or _now()
        interval = max(900, min(int(minimum_interval_seconds), 86400))
        events = self.recent_events(limit=30)
        turns = [
            event for event in events
            if event["event_type"] == "conversation_turn"
        ][:10]
        if not turns:
            return None
        appraisals = []
        for event in turns:
            try:
                appraisals.append(json.loads(event["appraisal_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
        if not appraisals:
            return None
        state_snapshot = asdict(self.get_state(now=current))
        with closing(self._connect()) as connection, connection as db:
            row = db.execute(
                "SELECT value FROM cognitive_meta WHERE key='last_reflection_at'"
            ).fetchone()
            if row is not None:
                try:
                    last_time = datetime.fromisoformat(row["value"])
                    if (current - last_time).total_seconds() < interval:
                        return None
                except ValueError:
                    pass
            obstacles = sum(bool(item.get("obstruction")) for item in appraisals)
            progress = sum(bool(item.get("progress")) for item in appraisals)
            uncertainty = sum(
                float(item.get("uncertainty", 0)) for item in appraisals
            ) / len(appraisals)
            summary = (
                f"Reviewed {len(appraisals)} recent interaction event(s): "
                f"{progress} progress cue(s), {obstacles} obstacle cue(s); "
                f"mean uncertainty signal {uncertainty:.2f}. "
                "This summary is an outcome record, not private reasoning."
            )
            db.execute(
                """INSERT INTO cognitive_events
                (id,conversation_id,event_type,appraisal_json,state_json,created_at)
                VALUES(?,NULL,'reflection',?,?,?)""",
                (uuid.uuid4().hex, json.dumps({"summary": summary}),
                 json.dumps(state_snapshot), _timestamp(current)),
            )
            db.execute(
                """INSERT INTO cognitive_meta(key,value) VALUES('last_reflection_at',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (_timestamp(current),),
            )
        return summary

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection as db:
            rows = db.execute(
                "SELECT * FROM cognitive_events ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]
