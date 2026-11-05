import unittest

from pathlib import Path

from support import temporary_directory
from v.identity import IdentityStore


class IdentityStoreTests(unittest.TestCase):
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
