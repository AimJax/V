import unittest
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone
from pathlib import Path

from support import temporary_directory
from v.cognition import CognitiveStore, appraise_event


class CognitiveStoreTests(unittest.TestCase):
    def test_action_risk_cues_are_specific_not_incidental(self):
        ordinary = appraise_event("Can you send me an example?")
        destructive = appraise_event("Please delete my files.")
        self.assertLess(ordinary.risk, destructive.risk)
        self.assertLess(destructive.reversibility, ordinary.reversibility)

    def test_appraisal_is_deterministic_and_explainable(self):
        first = appraise_event("Why is this broken again?")
        second = appraise_event("Why is this broken again?")
        self.assertEqual(first, second)
        self.assertEqual(first.obstruction, 1.0)
        self.assertEqual(first.novelty, 0.35)
        self.assertTrue(first.rationale)
        self.assertGreater(first.risk, 0)
        self.assertGreaterEqual(first.reversibility, 0)
        self.assertLessEqual(first.expected_utility, 1)

    def test_state_transition_is_bounded_and_persistent(self):
        with temporary_directory() as temp:
            path = Path(temp) / "cognition.sqlite3"
            store = CognitiveStore(path)
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            appraisal, state = store.process_turn(
                "The build failed again; why?",
                "Let's inspect the error.",
                conversation_id="conversation-1",
                now=now,
            )
            restored = CognitiveStore(path).get_state(now=now)
        self.assertEqual(appraisal.obstruction, 1.0)
        self.assertGreater(state.frustration, 0)
        self.assertEqual(restored, state)
        self.assertTrue(-1 <= state.valence <= 1)
        for field in ("activation", "frustration", "curiosity", "confidence"):
            self.assertTrue(0 <= getattr(state, field) <= 1)

    def test_transient_state_decays_after_restart(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            _, initial = store.process_turn(
                "The build failed again. Why?",
                "We can fix it.",
                now=now,
            )
            later = store.get_state(now=now + timedelta(hours=3))
        self.assertLess(later.frustration, initial.frustration)
        self.assertLess(later.activation, initial.activation)

    def test_goals_are_persistent_and_status_is_explicit(self):
        with temporary_directory() as temp:
            path = Path(temp) / "cognition.sqlite3"
            store = CognitiveStore(path)
            goal = store.create_goal(
                "Finish Phase 3",
                origin="user_requested",
                rationale="Explicit user request.",
                priority=0.9,
            )
            store.update_goal(goal.id, "deferred", rationale="Waiting for tests.")
            restored = CognitiveStore(path).list_goals(status="deferred")
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].id, goal.id)
        self.assertEqual(restored[0].origin, "user_requested")

    def test_goal_validation_and_execution_boundary(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            with self.assertRaises(ValueError):
                store.create_goal("Unsafe", origin="execute_shell")
            with self.assertRaises(ValueError):
                store.create_goal("Unreviewed candidate", origin="v_candidate")
            with self.assertRaises(ValueError):
                store.create_goal("", priority=0.5)

    def test_durable_preference_requires_evidence_and_review(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            with self.assertRaises(ValueError):
                store.propose_preference(
                    "Likes astronomy.", evidence_refs=(),
                    confidence=0.8, rationale="Insufficient evidence.",
                )
            identifier = store.propose_preference(
                "Prefers concise explanations.",
                evidence_refs=("conversation:abc/message:4", "conversation:def/message:8"),
                confidence=0.82,
                rationale="Repeated explicit requests.",
            )
            self.assertEqual(store.list_preferences()[0]["status"], "pending")
            store.review_preference(identifier, accept=True)
            self.assertEqual(store.list_preferences(status="accepted")[0]["id"], identifier)

    def test_candidate_goal_requires_evidence_and_user_review(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            with self.assertRaises(ValueError):
                store.propose_goal(
                    "Explore a new project",
                    evidence_refs=("chat:1",),
                    rationale="Only one ambiguous mention.",
                )
            proposal = store.propose_goal(
                "Explore a new project",
                evidence_refs=("chat:1", "chat:2"),
                rationale="Repeated explicit interest.",
            )
            self.assertEqual(store.list_goals(status="active"), [])
            self.assertEqual(store.list_goal_proposals()[0]["status"], "pending")
            accepted = store.review_goal_proposal(proposal, accept=True)
            self.assertEqual(accepted.origin, "v_candidate")
            self.assertEqual(store.list_goals(status="active")[0].id, accepted.id)

    def test_preference_requires_two_distinct_evidence_references(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            with self.assertRaises(ValueError):
                store.propose_preference(
                    "Has a stable preference.",
                    evidence_refs=("same-source", "same-source"),
                    confidence=0.8, rationale="Not corroborated.",
                )

    def test_goal_ranking_and_bounded_reflection(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            goal = store.create_goal("Fix desktop UI", priority=0.6)
            store.create_goal("Study astronomy", priority=0.9)
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            store.process_turn(
                "The desktop UI is broken again.",
                "Let's fix the layout.",
                now=now,
            )
            ranked = store.rank_goals("desktop UI")
            summary = store.reflect(now=now + timedelta(hours=1))
            throttled = store.reflect(now=now + timedelta(hours=1, minutes=1))
        self.assertEqual(ranked[0][0].id, goal.id)
        self.assertIn("obstacle cue", summary)
        self.assertIsNone(throttled)

    def test_reflection_throttle_survives_more_than_thirty_new_events(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            store.process_turn("The build failed.", "Let's inspect.", now=now)
            first = store.reflect(now=now + timedelta(hours=1))
            for index in range(35):
                store.process_turn(
                    "The build still has an error.",
                    "We should isolate the cause.",
                    now=now + timedelta(hours=1, minutes=1, seconds=index),
                )
            second = store.reflect(now=now + timedelta(hours=1, minutes=2))
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_context_only_surfaces_relevant_active_goals(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            store.create_goal("Fix desktop UI", priority=0.6)
            store.create_goal("Study astronomy", priority=0.9)
            context = store.render_context(query="The desktop UI needs attention.")
        self.assertIn("Fix desktop UI", context)
        self.assertNotIn("Study astronomy", context)

    def test_accepted_preferences_enter_context_but_pending_do_not(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            pending = store.propose_preference(
                "Prefers direct technical explanations.",
                evidence_refs=("chat:1", "chat:2"), confidence=0.8, rationale="Repeated observation.",
            )
            self.assertNotIn("direct technical explanations", store.render_context())
            store.review_preference(pending, accept=True)
            context = store.render_context()
        self.assertIn("User-reviewed preferences", context)
        self.assertIn("direct technical explanations", context)
        self.assertIn("consider counterevidence", context)

    def test_repeated_obstacles_increase_pressure_without_unbounded_state(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            _, first = store.process_turn("The build failed again.", "Let's inspect.", now=now)
            _, second = store.process_turn(
                "The build is still broken.", "We should isolate the error.",
                now=now + timedelta(minutes=1),
            )
        self.assertGreater(second.frustration, first.frustration)
        self.assertLessEqual(second.frustration, 1.0)

    def test_memory_salience_is_persistent_bounded_and_decays(self):
        with temporary_directory() as temp:
            path = Path(temp) / "cognition.sqlite3"
            store = CognitiveStore(path)
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            appraisal = appraise_event(
                "This is relevant to the project. Why?",
                active_goal_titles=("project",),
            )
            store.record_memory_salience(
                ("memory-a",), appraisal, now=now
            )
            restored = CognitiveStore(path)
            score = restored.memory_salience("memory-a", now=now)
            later = restored.memory_salience(
                "memory-a", now=now + timedelta(hours=6)
            )
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 1)
        self.assertGreaterEqual(later, 0)
        self.assertAlmostEqual(later, score * 0.5, places=5)

    def test_salience_only_advances_an_existing_retrieval_result(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            appraisal = appraise_event("Why is the project blocked?")
            for _ in range(3):
                store.record_memory_salience(("memory-b",), appraisal, now=now)
            memories = [
                SimpleNamespace(id="memory-a"),
                SimpleNamespace(id="memory-b"),
                SimpleNamespace(id="memory-c"),
            ]
            ordered = store.prioritize_memories(memories, now=now)
        self.assertEqual([item.id for item in ordered][0], "memory-b")
        self.assertEqual({item.id for item in ordered}, {"memory-a", "memory-b", "memory-c"})

    def test_context_is_compact_and_disclaims_subjective_feeling(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            context = store.render_context(max_characters=240)
        self.assertLessEqual(len(context), 240)
        self.assertIn("not subjective feelings", context)

    def test_schema_v1_upgrades_additively_without_losing_state(self):
        import sqlite3
        with temporary_directory() as temp:
            path = Path(temp) / "cognition.sqlite3"
            store = CognitiveStore(path)
            now = datetime(2026, 11, 8, tzinfo=timezone.utc)
            _, before = store.process_turn("The build is working now.", "Good.", now=now)
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "UPDATE cognitive_meta SET value='1' WHERE key='schema_version'"
                )
                connection.commit()
            finally:
                connection.close()
            upgraded = CognitiveStore(path)
            after = upgraded.get_state(now=now)
            with sqlite3.connect(path) as db:
                version = db.execute(
                    "SELECT value FROM cognitive_meta WHERE key='schema_version'"
                ).fetchone()[0]
                salience_table = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='cognitive_memory_salience'"
                ).fetchone()
        self.assertEqual(version, "2")
        self.assertIsNotNone(salience_table)
        self.assertEqual(after, before)

    def test_newer_schema_is_rejected(self):
        import sqlite3
        with temporary_directory() as temp:
            path = Path(temp) / "cognition.sqlite3"
            CognitiveStore(path)
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "UPDATE cognitive_meta SET value='999' WHERE key='schema_version'"
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                CognitiveStore(path)


if __name__ == "__main__":
    unittest.main()
