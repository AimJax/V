import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path

from support import temporary_directory
from v.cognition import CognitiveStore, appraise_event


class CognitiveStoreTests(unittest.TestCase):
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

    def test_context_is_compact_and_disclaims_subjective_feeling(self):
        with temporary_directory() as temp:
            store = CognitiveStore(Path(temp) / "cognition.sqlite3")
            context = store.render_context(max_characters=240)
        self.assertLessEqual(len(context), 240)
        self.assertIn("not subjective feelings", context)

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
