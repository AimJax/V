import unittest

from pathlib import Path

from support import temporary_directory
from v.identity import IdentityStore


class IdentityStoreTests(unittest.TestCase):
    def test_newer_identity_schema_is_rejected_without_mutation(self):
        import sqlite3

        with temporary_directory() as temp:
            path = Path(temp) / "identity.sqlite3"
            IdentityStore(path)
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "UPDATE identity_profile SET schema_version = 999 WHERE identifier = 'v'"
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                IdentityStore(path)

    def test_seeded_identity_persists_across_restarts(self):
        with temporary_directory() as temp:
            path = Path(temp) / "identity.sqlite3"
            first = IdentityStore(path)
            initial = first.get_snapshot()

            second = IdentityStore(path)
            restored = second.get_snapshot()

        self.assertEqual(initial.identifier, "v")
        self.assertEqual(initial.display_name, "V")
        self.assertEqual(initial.revision, 1)
        self.assertEqual(restored.revision, initial.revision)
        self.assertEqual(
            [trait.description for trait in restored.traits],
            [trait.description for trait in initial.traits],
        )
        self.assertTrue(all(trait.foundational for trait in restored.traits))
        self.assertTrue(all(trait.origin == "seed" for trait in restored.traits))

    def test_model_proposal_requires_evidence(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")

            with self.assertRaisesRegex(ValueError, "evidence"):
                store.create_proposal(
                    category="interest",
                    description="Has developed an interest in astronomy.",
                    rationale="A possible recurring interest.",
                    evidence_refs=[],
                    confidence=0.7,
                    origin="model_proposed",
                )

    def test_user_proposal_must_be_reviewed_before_becoming_identity(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")
            proposal = store.create_proposal(
                category="interest",
                description="Has developed an interest in astronomy.",
                rationale="Explicitly suggested by the user.",
                evidence_refs=[],
                confidence=1.0,
                origin="user_stated",
            )

            self.assertEqual(len(store.get_snapshot().traits), 8)
            self.assertEqual(proposal.status, "pending")

            reviewed = store.review_proposal(proposal.id, decision="accept")
            snapshot = store.get_snapshot()

        self.assertEqual(reviewed.status, "accepted")
        self.assertEqual(snapshot.revision, 2)
        developed = [trait for trait in snapshot.traits if not trait.foundational]
        self.assertEqual(len(developed), 1)
        self.assertEqual(developed[0].origin, "user_stated")
        self.assertEqual(developed[0].status, "established")

    def test_model_proposal_is_only_committed_after_explicit_review(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")
            proposal = store.create_proposal(
                category="curiosity",
                description="Shows curiosity about astronomy.",
                rationale="Observed in multiple conversations.",
                evidence_refs=["conversation:abc/message:12"],
                confidence=0.82,
                origin="model_proposed",
            )

            self.assertFalse(
                any("astronomy" in trait.description for trait in store.get_snapshot().traits)
            )
            store.review_proposal(proposal.id, decision="accept")
            traits = store.get_snapshot().traits

        developed = [trait for trait in traits if not trait.foundational]
        self.assertEqual(developed[0].origin, "model_proposed")
        self.assertEqual(developed[0].evidence_refs, ("conversation:abc/message:12",))

    def test_rejected_and_deferred_proposals_do_not_create_traits(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")
            rejected = store.create_proposal(
                category="habit",
                description="Prefers to work late at night.",
                rationale="Candidate observation.",
                evidence_refs=["conversation:abc/message:4"],
                confidence=0.5,
                origin="behaviorally_observed",
            )
            deferred = store.create_proposal(
                category="preference",
                description="Prefers instrumental music.",
                rationale="Candidate observation.",
                evidence_refs=["conversation:abc/message:8"],
                confidence=0.6,
                origin="model_proposed",
            )

            store.review_proposal(rejected.id, decision="reject")
            store.review_proposal(deferred.id, decision="defer")
            snapshot = store.get_snapshot()
            proposal_statuses = {
                item.status for item in store.list_proposals(status="all")
            }

        self.assertEqual(len(snapshot.traits), 8)
        self.assertEqual(
            proposal_statuses,
            {"rejected", "deferred"},
        )

    def test_foundational_traits_cannot_be_changed_through_developed_trait_editor(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")
            trait = store.get_snapshot().traits[0]

            with self.assertRaisesRegex(ValueError, "Foundational"):
                store.update_trait(
                    trait.id,
                    description="A model rewrote the core identity.",
                )

    def test_foundational_trait_can_only_be_changed_with_explicit_user_authorization(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")
            trait = store.get_snapshot().traits[0]
            updated = store.update_trait(
                trait.id,
                description="User-approved correction to a seed trait.",
                allow_foundational=True,
                reviewer_note="Explicitly corrected by the user.",
            )

        self.assertTrue(updated.foundational)
        self.assertEqual(updated.origin, "user_stated")
        self.assertEqual(updated.description, "User-approved correction to a seed trait.")

    def test_developed_trait_can_be_corrected_with_revision_history(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")
            proposal = store.create_proposal(
                category="interest",
                description="Likes astronomy.",
                rationale="User-provided proposal.",
                evidence_refs=[],
                confidence=1.0,
                origin="user_stated",
            )
            store.review_proposal(proposal.id, decision="accept")
            trait = next(
                item for item in store.get_snapshot().traits
                if not item.foundational
            )

            updated = store.update_trait(
                trait.id,
                description="Enjoys learning about planetary science.",
                reviewer_note="Corrected wording.",
            )
            snapshot = store.get_snapshot()

        self.assertEqual(updated.description, "Enjoys learning about planetary science.")
        self.assertEqual(snapshot.revision, 3)

    def test_context_is_bounded_and_only_includes_established_traits(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")
            context = store.render_context(max_characters=1800)

        self.assertLessEqual(len(context), 1800)
        self.assertIn("Persistent identity context", context)
        self.assertIn("honesty", context.casefold())

    def test_identity_backup_round_trip_preserves_traits_proposals_and_history(self):
        with temporary_directory() as temp:
            root = Path(temp)
            source = IdentityStore(root / "source.sqlite3")
            proposal = source.create_proposal(
                category="interest",
                description="Enjoys astronomy.",
                rationale="Explicit user proposal.",
                evidence_refs=[],
                confidence=1.0,
                origin="user_stated",
            )
            source.review_proposal(proposal.id, decision="accept")
            backup = source.export_backup(root / "identity.json")

            restored = IdentityStore(root / "restored.sqlite3")
            snapshot = restored.import_backup(backup, replace=True)
            history_count = len(restored.list_revisions())
            proposal_status = restored.list_proposals(status="all")[0].status

        self.assertEqual(snapshot.revision, 2)
        self.assertTrue(any("astronomy" in trait.description for trait in snapshot.traits))
        self.assertEqual(history_count, 2)
        self.assertEqual(proposal_status, "accepted")

    def test_identity_restore_requires_explicit_replacement(self):
        with temporary_directory() as temp:
            root = Path(temp)
            store = IdentityStore(root / "identity.sqlite3")
            backup = store.export_backup(root / "identity.json")

            with self.assertRaisesRegex(ValueError, "replace=True"):
                store.import_backup(backup)

    def test_invalid_identity_backup_does_not_replace_existing_state(self):
        import json

        with temporary_directory() as temp:
            root = Path(temp)
            store = IdentityStore(root / "identity.sqlite3")
            before = store.get_snapshot()
            invalid = root / "invalid.json"
            invalid.write_text(
                json.dumps({"format": "not-an-identity-backup"}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                store.import_backup(invalid, replace=True)
            after = store.get_snapshot()

        self.assertEqual(after.revision, before.revision)
        self.assertEqual(
            [trait.description for trait in after.traits],
            [trait.description for trait in before.traits],
        )

    def test_validation_rejects_invalid_categories_and_confidence(self):
        with temporary_directory() as temp:
            store = IdentityStore(Path(temp) / "identity.sqlite3")

            with self.assertRaises(ValueError):
                store.create_proposal(
                    category="unrestricted",
                    description="Invalid category.",
                    rationale="No.",
                    evidence_refs=[],
                    confidence=1.0,
                    origin="user_stated",
                )

            with self.assertRaises(ValueError):
                store.create_proposal(
                    category="interest",
                    description="Invalid confidence.",
                    rationale="No.",
                    evidence_refs=[],
                    confidence=float("nan"),
                    origin="user_stated",
                )


if __name__ == "__main__":
    unittest.main()
