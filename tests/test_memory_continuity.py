from __future__ import annotations

import sqlite3

from contextlib import closing

import pytest

from v.memory.continuity import ContinuityStore


@pytest.fixture
def continuity(tmp_path):
    path = tmp_path / "memory.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, memory_type TEXT, subject TEXT, content TEXT, source_conversation_id TEXT, source_message_id INTEGER, provenance TEXT, confidence REAL)")
    db.executemany(
        "INSERT INTO memories VALUES (?, 'fact', 'subject', ?, 'conversation', ?, 'explicit', 1.0)",
        [("m1", "first", 1), ("m2", "second", 2), ("derived", "summary", 3)],
    )
    db.commit()
    db.close()
    return ContinuityStore(path)



def test_current_and_historical_recall_survive_store_restart(tmp_path):
    from v.memory.retrieval import retrieve_relevant_memories
    from v.memory.store import MemoryStore

    database = tmp_path / "memory.sqlite3"
    store = MemoryStore(database)
    continuity = ContinuityStore(database)

    older = store.create_memory(
        content="The user worked at Site A as a field technician.",
        memory_type="episodic",
        subject="User",
        memory_key="user.work_context",
        source_conversation_id="conversation-old",
        source_message_id=11,
        source_created_at="2024-03-01T09:00:00+00:00",
        evidence="I worked at Site A.",
    )
    current = store.create_memory(
        content="The user works at Site B as a research coordinator.",
        memory_type="episodic",
        subject="User",
        memory_key="user.work_context",
        source_conversation_id="conversation-current",
        source_message_id=22,
        source_created_at="2026-10-01T09:00:00+00:00",
        evidence="I work at Site B.",
    )
    continuity.set_memory_state(
        older.id,
        "superseded",
        superseded_by=current.id,
        note="A later work-context statement replaced this snapshot.",
    )

    # Reopen both stores to simulate a new application session.
    reopened = MemoryStore(database)
    reopened_continuity = ContinuityStore(database)
    assert reopened_continuity.temporal_record(older.id)["state"] == "superseded"

    present = retrieve_relevant_memories(
        reopened,
        "Where does the user work now?",
        limit=5,
    )
    history = retrieve_relevant_memories(
        reopened,
        "Where did the user work previously?",
        limit=5,
    )

    present_ids = {item.id for item in present}
    history_ids = {item.id for item in history}
    assert current.id in present_ids
    assert older.id not in present_ids
    assert {older.id, current.id}.issubset(history_ids)

def test_temporal_validity_and_state_are_timezone_aware(continuity):
    record = continuity.ensure_temporal_record(
        "m1", valid_from="2026-01-01T00:00:00+07:00",
        valid_until="2026-02-01T00:00:00+07:00",
    )
    assert record["valid_from"].endswith("+00:00")
    assert record["state"] == "current"
    changed = continuity.set_memory_state(
        "m1", "superseded", superseded_by="m2", note="Circumstance changed"
    )
    assert changed["superseded_by"] == "m2"


def test_rejects_invalid_temporal_ranges_and_unknown_ids(continuity):
    with pytest.raises(ValueError):
        continuity.ensure_temporal_record(
            "m1", valid_from="2026-02-01T00:00:00+00:00",
            valid_until="2026-01-01T00:00:00+00:00",
        )
    with pytest.raises(ValueError):
        continuity.ensure_temporal_record("m1", valid_from="2026-01-01T00:00:00")
    with pytest.raises(KeyError):
        continuity.ensure_temporal_record("missing")



def test_atomic_temporal_update_can_clear_validity_dates(continuity):
    continuity.ensure_temporal_record(
        "m1",
        valid_from="2026-01-01T00:00:00+00:00",
        valid_until="2026-02-01T00:00:00+00:00",
    )
    updated = continuity.update_temporal_record(
        "m1",
        "current",
        valid_from=None,
        valid_until=None,
        note="Validity is no longer bounded.",
    )
    assert updated["valid_from"] is None
    assert updated["valid_until"] is None
    assert updated["note"] == "Validity is no longer bounded."


def test_atomic_temporal_update_rejects_invalid_transition_without_partial_write(continuity):
    original = continuity.ensure_temporal_record(
        "m1", valid_from="2026-01-01T00:00:00+00:00"
    )
    with pytest.raises(ValueError):
        continuity.update_temporal_record(
            "m1",
            "superseded",
            valid_from="2026-02-01T00:00:00+00:00",
            valid_until="2026-01-01T00:00:00+00:00",
            superseded_by="m2",
        )
    unchanged = continuity.temporal_record("m1")
    assert unchanged == original

def test_derivations_require_existing_sources_and_explicit_review(continuity):
    assert continuity.add_derivation("derived", ["m1", "m2"]) == 2
    sources = continuity.derivation_sources("derived")
    assert len(sources) == 2
    assert {item["state"] for item in sources} == {"pending"}
    assert continuity.review_derivation("derived", "accepted") == 2
    assert {item["state"] for item in continuity.derivation_sources("derived")} == {"accepted"}
    with pytest.raises(ValueError):
        continuity.add_derivation("derived", ["m1", "m1"])
    with pytest.raises(KeyError):
        continuity.add_derivation("derived", ["missing"])



def test_supersession_requires_a_distinct_replacement(continuity):
    with pytest.raises(ValueError):
        continuity.set_memory_state("m1", "superseded")
    with pytest.raises(ValueError):
        continuity.set_memory_state("m1", "current", superseded_by="m2")
    with pytest.raises(ValueError):
        continuity.set_memory_state("m1", "superseded", superseded_by="m1")
    with pytest.raises(KeyError):
        continuity.set_memory_state("m1", "superseded", superseded_by="missing")



def test_supersession_chains_cannot_form_cycles(continuity):
    continuity.set_memory_state("m1", "superseded", superseded_by="m2")
    with pytest.raises(ValueError, match="cycle"):
        continuity.set_memory_state("m2", "superseded", superseded_by="m1")
    assert continuity.temporal_record("m2")["state"] == "current"

def test_derivation_source_list_is_bounded_and_well_formed(continuity):
    with pytest.raises(ValueError):
        continuity.add_derivation("derived", "m1")
    with pytest.raises(ValueError):
        continuity.add_derivation("derived", [""])
    with pytest.raises(ValueError):
        continuity.add_derivation("derived", ["m1"] * 101)


def test_source_edit_invalidates_accepted_derivation_and_marks_summary_disputed(continuity):
    continuity.add_derivation("derived", ["m1", "m2"])
    continuity.review_derivation("derived", "accepted")

    with closing(sqlite3.connect(continuity.database_path)) as db:
        db.execute("UPDATE memories SET content='corrected source' WHERE id='m1'")
        db.commit()

    sources = continuity.derivation_sources("derived")
    assert {item["state"] for item in sources} == {"rejected"}
    with closing(sqlite3.connect(continuity.database_path)) as db:
        state = db.execute(
            "SELECT state FROM memory_temporal WHERE memory_id='derived'"
        ).fetchone()[0]
    assert state == "disputed"



def test_source_edit_invalidates_pending_derivation_before_user_review(continuity):
    continuity.add_derivation("derived", ["m1", "m2"])
    with closing(sqlite3.connect(continuity.database_path)) as db:
        db.execute("UPDATE memories SET content='corrected source' WHERE id='m1'")
        db.commit()

    assert {item["state"] for item in continuity.derivation_sources("derived")} == {"rejected"}
    assert continuity.temporal_record("derived")["state"] == "disputed"

def test_source_deletion_marks_dependent_summary_disputed(continuity):
    continuity.add_derivation("derived", ["m1", "m2"])
    continuity.review_derivation("derived", "accepted")

    with closing(sqlite3.connect(continuity.database_path)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("DELETE FROM memories WHERE id='m1'")
        db.commit()

    with closing(sqlite3.connect(continuity.database_path)) as db:
        state = db.execute(
            "SELECT state FROM memory_temporal WHERE memory_id='derived'"
        ).fetchone()[0]
        remaining_links = db.execute(
            "SELECT COUNT(*) FROM memory_derivations "
            "WHERE derived_memory_id='derived' AND state='rejected'"
        ).fetchone()[0]
    assert state == "disputed"
    # The deleted source link cascades away; surviving links remain rejected.
    assert remaining_links == 1

def test_commitments_track_due_dates_and_lifecycle(continuity):
    item = continuity.create_commitment(
        "Review the memory export", due_at="2026-11-10T12:00:00+07:00",
        source_memory_id="m1",
    )
    assert item["state"] == "open"
    assert len(continuity.list_commitments()) == 1
    completed = continuity.update_commitment(item["id"], "completed")
    assert completed["state"] == "completed"
    assert continuity.list_commitments() == []
    assert len(continuity.list_commitments(state="all")) == 1



def test_temporal_derivation_and_commitment_state_survive_store_restart(continuity):
    continuity.add_derivation("derived", ["m1", "m2"])
    continuity.review_derivation("derived", "accepted")
    continuity.update_temporal_record(
        "derived",
        "current",
        valid_from="2026-01-01T00:00:00+00:00",
        note="Reviewed summary.",
    )
    commitment = continuity.create_commitment(
        "Continue the memory evaluation",
        due_at="2026-11-12T09:00:00+07:00",
        source_memory_id="m1",
    )

    reopened = ContinuityStore(continuity.database_path)

    assert reopened.temporal_record("derived")["note"] == "Reviewed summary."
    assert {item["state"] for item in reopened.derivation_sources("derived")} == {"accepted"}
    assert reopened.list_commitments(state="all")[0]["id"] == commitment["id"]

def test_commitment_rejects_bad_dates_and_missing_source(continuity):
    with pytest.raises(ValueError):
        continuity.create_commitment("   ")
    with pytest.raises(ValueError):
        continuity.create_commitment("A date without timezone", due_at="2026-11-10T12:00:00")
    with pytest.raises(KeyError):
        continuity.create_commitment("Missing source", source_memory_id="missing")
