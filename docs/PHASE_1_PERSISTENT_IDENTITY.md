# Phase 1 — Persistent Identity

**Status:** In progress  
**Priority:** First implementation phase  
**Objective:** Give V a durable identity independent of the active system prompt, model, conversation, and application process.

## Implementation status on the active branch

The first implementation slice is now present:

- A separate local SQLite identity database at `data/identity/identity.sqlite3`; it does not reuse or duplicate the memory database.
- A versioned identity profile, foundational seed traits, developed traits, reviewable proposals, and an append-only revision event history.
- Initial seed traits derived from checked-in personality and product philosophy guidance, with source references.
- Bounded identity context injected into both CLI and desktop chat assembly.
- User-facing desktop Identity Manager for inspecting traits, proposing changes, reviewing proposals, editing traits, and inspecting revision history.
- Explicit accept/reject/defer workflow. Model/behavior proposals require evidence references; they do not alter identity until reviewed.
- Explicit user corrections can edit foundational traits; ordinary proposal acceptance can only add developed traits.
- Versioned JSON export and validated restore. Restore requires an explicit confirmation and replaces identity data; backups are plaintext and remain local unless the user chooses another destination.
- CLI commands for identity inspection, proposal creation, and review.
- Conservative local identity-development review, run every configured number of assistant turns using the configured local model. It analyzes bounded recent conversation records, requires exact excerpts from at least two distinct V assistant messages, rejects unsupported or low-confidence candidates, deduplicates existing traits/proposals, and queues suggestions for explicit user review. It never commits a model-generated identity change automatically.
- Identity review runs as cancellable background work in the desktop runtime and yields to the next user turn; the CLI performs the review after the configured interval.

Still required before Phase 1 can be marked verified:

- Run the full Windows CI suite successfully on the final commit and resolve any failures.
- Complete an end-to-end manual desktop check on the target Windows installation.
- Verify continuity after changing the configured local model and restarting V.
- Run the full Windows CI suite successfully against the final implementation commit.
- Complete an end-to-end manual desktop check on the target Windows installation.
- Verify continuity after changing the configured local model and restarting V.
- Verify the automatic review cadence and proposal quality with real local-model conversations. The automated tests validate evidence gates and lifecycle behavior, but cannot establish the quality of the selected model's judgments.
- Review migration and backup recovery behavior against real user data before declaring the phase complete.

## Target-machine sign-off checklist

The automated Windows workflow validates the code on a clean runner. Complete these checks on the actual `G:\\V` installation before changing the phase status to **verified**:

1. Update the existing `network-policy-and-offline-mode` checkout with a fast-forward pull; do not reset or replace the working directory.
2. Run the project test suite from the existing virtual environment:
   ```powershell
   & "G:/V/.venv/Scripts/python.exe" -m pytest -q
   ```
3. Launch the desktop app:
   ```powershell
   & "G:/V/.venv/Scripts/python.exe" -m v desktop
   ```
4. Open **Identity** in the sidebar. Confirm that the foundational traits, revision number, proposed-changes tab, revision-history tab, and backup controls render correctly.
5. Complete at least five assistant turns across saved conversations. Allow the local background review to finish, then reopen or refresh Identity and inspect any proposed changes. Confirm that candidates cite at least two distinct assistant-message IDs and that none are applied without explicit acceptance.
6. Accept one disposable test proposal, restart V, and confirm that the developed trait and revision persist. Reject or defer another proposal and confirm it does not become a trait.
7. If another local model is already installed, switch the configured model and restart V. Confirm that the identity revision and traits remain unchanged.
8. Export a plaintext identity backup to a private local location. Restore it only after confirming that the selected backup is the intended one; verify that traits, proposals, and revision history are restored.
9. Confirm that `data/identity/identity.sqlite3` and exported backups remain outside Git.

Automatic development can be disabled without removing identity persistence by setting `[identity].automatic_development = false` in local configuration. The default review interval is every five assistant responses across saved conversations; candidates remain pending until explicitly reviewed.

## 1. Intended result

V should have a stable identity loaded at startup, supplied selectively to the conversation runtime, inspectable, and safely evolvable. Identity is not a transcript summary or a personality prompt. It is structured application state with explicit semantics, versioning, provenance, and controlled update rules.

A model change must not silently redefine V. Editing a prompt must not erase identity or history. Temporary mood, conversational adaptation, user facts, and application capabilities must not become permanent identity traits.

## 2. Existing foundation to reuse

The active branch already has `config/personality.md`, desktop personality settings, SQLite persistence and migration patterns, and `docs/PRODUCT_PHILOSOPHY.md`. Audit these first. Keep the personality file as human-authored communication guidance, but do not make it the sole identity store. Do not create a parallel general-purpose memory database.

## 3. Identity domain model

Choose a versioned document or normalized records after reviewing existing persistence patterns. At minimum represent:

### 3.1 Foundational identity

- Stable identifier and display name.
- Schema version and record revision.
- Initial temperament and communication tendencies.
- Foundational values, principles, and behavioral boundaries.
- Initial interests and curiosity.
- Interaction style and aesthetic preferences, where defined.
- Explicit distinction between seed traits and traits developed through experience.

Foundational traits may evolve deliberately, but an ordinary model completion must never rewrite them.

### 3.2 Developed traits and preferences

Each developed trait should include:

- Category and human-readable description.
- Lifecycle status: tentative, established, challenged, retired, or superseded.
- Evidence references to conversations or memory records.
- Confidence/strength and first-observed/last-reviewed timestamps.
- Origin: seed, user-stated, model-proposed, or behaviorally observed.
- Concise rationale and revision history.

Repeated behavior may support a tentative preference, but frequency alone must not turn a generated claim into fact. Conflicting evidence should remain visible.

### 3.3 Identity boundaries

Keep identity separate from episodic/semantic memory, temporary affect, task context, active goals, live sensor observations, runtime capabilities, permissions, and security policy. Identity may reference these domains but must not duplicate or override their authoritative records.

## 4. Runtime integration

Implement a dedicated identity service that:

1. Loads and validates identity at startup.
2. Provides a read-only identity snapshot to conversation assembly.
3. Selects relevant identity details within a predictable token budget.
4. Keeps authoritative identity out of ordinary editable prompt text where possible.
5. Exposes identity state for inspection and user-approved edits.
6. Stores proposed evolution as reviewable changes rather than overwriting core state.
7. Handles missing optional fields and recoverable migrations safely.

Do not add an unbounded scan or an extra model request to every chat turn merely to reconstruct identity. Cache snapshots safely and invalidate them after committed changes.

## 5. Identity evolution workflow

Implement this lifecycle:

1. **Observe:** A conversation or repeated behavior provides evidence for a possible trait or preference.
2. **Propose:** Create a candidate change with source references and rationale.
3. **Evaluate:** Check duplicates, contradictions, sensitivity, recency, and whether evidence supports a durable trait rather than a temporary state.
4. **Review:** Present proposals for inspection. Sensitive, foundational, or consequential changes require explicit approval. V must not be forced to accept a characterization merely because it was suggested.
5. **Commit:** Save an accepted change with provenance and revision history.
6. **Reconcile:** Later conflicting evidence can challenge or revise a trait without erasing its history.

Define which low-risk changes may be accepted automatically before enabling automatic evolution. Foundational values and safety boundaries must never be silently rewritten by the model.

## 6. User-facing controls

The desktop application should provide an identity overview, separation of foundational and developed traits, evidence inspection, accept/edit/reject/defer controls, revision history, correction, backup/export, and an explanation of what identity information enters model context.

Do not expose private reflections indiscriminately. Identity transparency does not require publishing every internal note.

## 7. Persistence, migration, and recovery

- Use schema versioning and deterministic migrations.
- Do not alter the meaning of existing conversation or memory records.
- Keep identity backups separate from disposable caches.
- Validate imported data; reject malformed, oversized, or unsupported critical versions.
- Preserve the previous valid state if migration/import fails.
- Never commit private identity data, user records, or runtime databases to Git.

## 8. Security and privacy

Treat model-generated proposals as untrusted. Validate fields, lengths, categories, references, and transitions in application code. Identity content must not grant tools, network, filesystem, or sensor permissions. Do not infer sensitive personal traits for storage. Keep records local and make correction/deletion behavior explicit.

## 9. Implementation milestones

1. Audit chat, configuration, persistence, desktop settings, and memory interfaces.
2. Specify the schema and distinctions between identity, memory, affect, and capabilities.
3. Implement storage, validation, versioning, and migrations.
4. Implement read-only identity service and bounded chat-context integration.
5. Implement proposal/review/commit for identity evolution.
6. Add desktop inspection and editing.
7. Add backup/restore and recovery documentation.
8. Verify continuity across sessions and model changes.

## 10. Required tests

- Identity loads consistently across restarts.
- Model/provider changes do not reset identity.
- Editing `config/personality.md` does not overwrite structured identity.
- Temporary tone or mood does not automatically become a durable trait.
- Every developed trait traces to evidence or an explicit seed.
- Conflicting evidence does not silently delete history.
- Invalid model proposals cannot modify authoritative identity.
- Foundational traits cannot be overwritten by ordinary model output.
- Context assembly is bounded and avoids duplicating memory/capability data.
- Migrations preserve existing data; failed imports leave valid state intact.
- Identity data remains local and excluded from Git.

## 11. Acceptance criteria

Phase 1 is verified only when V has a versioned identity separate from prompts, conversations, memory, affect, and runtime capabilities; identity survives restarts and model/provider changes; developed traits have evidence and revision history; evolution follows an enforced review/commit lifecycle; desktop inspection/editing works; and required tests pass on supported Windows.

## 12. Explicitly out of scope

Full autobiographical memory consolidation (Phase 2), cognitive/affective dynamics (Phase 3), multimodal perception and wake phrase (Phase 4), and proactive/background activity (Phase 5). Persistent identity is not evidence of subjective consciousness.
