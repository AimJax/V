# Phase 2 — Memory and Continuity

**Status:** In progress  
**Objective:** Evolve the existing memory implementation into coherent, time-aware autobiographical continuity without replacing working infrastructure or weakening evidence quality.

## Implementation status on the active branch

**Status remains In progress.** The current branch now contains the following implementation:

- The existing SQLite memory store remains authoritative; temporal and prospective metadata are additive tables in the same database.
- Temporal records support current, superseded, corrected, disputed, and expired states; timezone-aware validity windows; and explicit replacement references.
- Temporal lifecycle and validity can be changed atomically. Invalid transitions, self-supersession, and malformed source references are rejected.
- Evidence-linked derivations are review-gated. New inferred patterns created while continuity is enabled are pending by default. Existing inferred patterns are migrated from their explicit evidence links into pending review.
- Editing or deleting source evidence invalidates accepted dependent derivations. Dependent summaries are marked disputed when they remain in storage.
- Procedural memories are a first-class type for explicit, repeatable user workflows and conventions. Extraction guidance explicitly prevents treating stored procedures as permission to perform consequential actions.
- Prospective commitments are extracted only from explicit user-stated future intent or reminder requests, with exact source quotations and source-memory links. They support due dates, descriptive recurrence, and open/completed/cancelled states. Relevant open commitments are selectively injected into chat context; completed commitments are available to historical queries. They are stored as commitments only; they are not scheduled reminders or automations.
- Backup format v4 exports and restores temporal records, derivations, and commitments in addition to memories and inferred-pattern evidence. Import remains compatible with v1, v2, and v3 backups, validates references, and merges atomically.
- Present-focused retrieval excludes non-current or out-of-validity records and excludes derived records with pending/rejected provenance. Historical queries can still retrieve past or disputed records. Retrieval remains lexical-first with the existing semantic/relationship infrastructure and bounded context assembly.
- Elliptical follow-up questions can use the two most recent user turns from the same conversation to resolve references. This is activated only by follow-up cues; standalone questions are not mixed with unrelated history. The recall preview uses the same contextual query builder as chat.
- The desktop Memory Manager now opens a continuity view for a selected memory. It exposes a chronological timeline grouped by topic key or memory type, temporal lifecycle editing, validity dates, derivation-source inspection/review, and commitment creation/completion/cancellation.
- Contextual retrieval resolves elliptical follow-ups from recent user turns while leaving standalone queries untouched. Direct matches retain priority over optional associations.
- A read-only recall preview runs the same contextual retrieval path as chat and displays the actual retrieval query, selected memories, selected commitments, source quotations, and the assembled memory-context block.
- A local-model consolidation pipeline groups related explicit memories, preserves source references, and creates inferred-pattern proposals. Each proposal remains pending review and is excluded from ordinary retrieval until accepted.
- Consolidation runs as cancellable background work, yields to interactive chat, and does not compete with the historical backfill worker for the local model.

The remaining verification gate is a target-machine smoke test with the configured local model and GPU, followed by a final review of the multi-session, backup/restore, and lifecycle acceptance checklist. Phase 2 remains In progress until that gate passes.

## 1. Intended result

V should retain relevant understanding across days, conversations, interruptions, and restarts. Memory should preserve experiences, changing circumstances, ongoing projects, decisions, unresolved questions, preferences, and the context that gives them meaning—not merely isolated facts.

The goal is appropriate recall in ordinary conversation, not maximal storage, constant memory announcements, or a large prompt dump.

## 2. Existing foundation to reuse

The active branch already has SQLite memory, explicit extraction with exact source quotations, provenance/confidence/importance/timestamps, review proposals and conflict handling, historical backfill, FTS5 and local semantic retrieval, structural relationships, inferred-pattern evidence tracking, correction/deletion invalidation, versioned backup/restore, and desktop memory management.

Begin with a code-level audit of these services and tests. Extend them incrementally. Do not build a second memory store or weaken explicit-evidence rules.

## 3. Memory categories and semantics

### 3.1 Episodic memory

A record of a particular event or interaction: what happened, when, context, participants/entities, source conversation/message or sensor references, direct observation versus later interpretation, importance, confidence, and temporal validity. Summaries must link to underlying evidence and must not rewrite the source event.

### 3.2 Semantic memory

Relatively stable knowledge about entities, projects, preferences, and relationships. It must derive from supported evidence, carry provenance, and support correction as circumstances change.

### 3.3 Procedural memory

Reusable knowledge about recurring workflows, user-approved conventions, and project-specific procedures. A stored procedure is not permission to perform consequential actions without current authorization.

### 3.4 Prospective memory

Future-oriented commitments, reminders, pending decisions, deadlines, and agreed follow-ups. Track status, due time, recurrence, source, and completion/cancellation. Distinguish an intention from a confirmed scheduled automation.

### 3.5 Autobiographical continuity

A time-ordered account of significant experiences and developments relevant to V's identity and relationship context. This is a derived navigation layer over evidence-backed memories, not a fictional biography. The first implementation uses accepted, evidence-linked `inferred_pattern` records keyed by topic or episodic timeline rather than storing an independent narrative biography. Timeline consolidation preserves source chronology and remains pending review.

### 3.6 Affective associations

Links between events and functional affective appraisals may be stored only once the affect system exists (Phase 3) and can provide provenance. Do not fabricate emotions retrospectively.

## 4. Temporal reasoning and change

- Represent when a statement was true, when it was recorded, and when it was confirmed separately.
- Support superseded, corrected, disputed, expired, and current states.
- Do not treat a once-true statement as permanently current.
- Preserve historical context when a project, preference, or circumstance changes.
- Resolve conflicts with evidence and chronology; never silently overwrite.
- Preserve uncertainty when dates or state transitions are unknown.

## 5. Consolidation and association

Develop a bounded consolidation pipeline that identifies related records using existing relationships, produces candidate summaries/patterns with source references, detects duplicates and contradictions, preserves original source records, queues derived records for review or applies only explicit low-risk rules, and invalidates/recomputes dependent summaries when evidence changes or is deleted.

Model-generated summaries are interpretations, not source evidence. The database and UI must preserve that distinction.

## 6. Contextual retrieval

Improve retrieval beyond raw lexical/semantic similarity:

- Use current dialogue, active topic, entity references, time, and task context.
- Prefer current records for questions about present circumstances.
- Prefer original evidence when asked what was said or why a conclusion exists.
- Retrieve associated context only when it materially helps.
- Rank direct matches before optional associations.
- Enforce a strict context/token budget and avoid unrelated or sensitive over-retrieval.
- Provide lexical fallback if local embeddings are unavailable.
- Never block normal chat because retrieval failed.

Retrieval results must expose enough metadata to distinguish direct memory, derived summary, inference, and uncertain match.

## 7. Lifecycle and user controls

Extend existing controls for source inspection, correction with history, duplicate merge with audit trail, outdated/disputed status, deletion with dependent-record invalidation, export/restore, background job status, and inspection of what will enter model context.

Respect the existing review queue. Do not turn every model-generated interpretation into an accepted fact.

## 8. Performance and local operation

Run extraction, backfill, consolidation, and embedding work as cancellable background jobs. Interactive chat takes priority. Keep model use within 8 GB VRAM through sequential/lazy loading or CPU use where appropriate. Keep memory and embeddings local. Distinguish rebuildable caches from authoritative records. Use transactions and checkpoints for long operations.

## 9. Implementation milestones

1. **Implemented, CI verified:** Inventory existing memory schemas, extraction, retrieval, graph, backup, UI, and tests; preserve the existing SQLite infrastructure.
2. **Implemented, CI verified:** Define and persist temporal lifecycle, prospective commitments, and evidence-linked derivation states.
3. **Implemented, CI verified:** Add versioned continuity schema and v4 backup/restore with v1-v3 compatibility.
4. **Implemented, CI verified:** Enforce temporal validity, supersession, and dependent-record invalidation.
5. **Implemented, CI verified:** Evidence-linked consolidation proposals, duplicate avoidance, contradiction-aware summarization, and invalidation; local-model evaluation remains.
6. **Implemented, CI verified:** Present-focused validity filtering, review-gated derived retrieval, contextual follow-up resolution, and selective commitment recall; target-machine recall evaluation remains.
7. **Implemented, CI verified:** Desktop continuity inspection, subject timelines, temporal editing, derivation review, prospective commitment controls, and exact recall preview are connected to the runtime.
8. **Implemented, CI verified:** Multi-conversation, multi-session, restart, migration, backup/restore, and model-change evaluations; local model/GPU smoke testing remains.

## 10. Required tests

- Summaries never alter original source evidence.
- Every derived record identifies its supporting sources.
- Correcting/deleting evidence invalidates dependent conclusions correctly.
- Historical facts are not presented as current without evidence.
- Conflicts remain visible and are not silently overwritten.
- Follow-up references resolve without contaminating unrelated standalone turns.
- Direct matches rank ahead of optional associations.
- Retrieval failure does not prevent chat.
- Background work can pause, resume, cancel, and yield to interactive turns.
- Backup/restore preserves all supported types, provenance, and relationships.
- Migrations preserve existing memory and conversation data.

## 11. Local verification

Run from the project root with V's Python environment active:

- `python -m pytest` — complete automated test suite.
- `python -m v memory evaluate` — isolated synthetic retrieval benchmark.
- `python -m v memory evaluate --personal` — read-only evaluation against this PC's saved memories. Question generation and embedding calls use the configured local inference endpoint. Generated cases remain in memory; the command does not modify saved memories or the embedding cache.
- `python -m v desktop` — launch the desktop application for the runtime smoke test.

The personal evaluation is the required target-PC check after Windows CI. Close the V desktop before running the CLI evaluations to avoid competing local model workloads; the local chat and embedding endpoints must be configured and available. Review per-question misses and false positives before considering the configured retrieval threshold calibrated. The benchmark reports a candidate threshold but never changes configuration automatically.

### Desktop smoke-test checklist

Use a throwaway test conversation and synthetic details rather than introducing sensitive personal information.

1. Start V with the configured local chat and embedding models. Confirm both report ready without a cloud fallback.
2. State a clear future intention with a due date, such as: "I'll finish the local memory test by Friday." Allow the memory worker to process the message.
3. Open Memory Manager → Continuity. Confirm the commitment appears with its source-memory reference and exact source quotation. Confirm the UI states that no notification was scheduled.
4. Ask V what remains to be done. Confirm the relevant open commitment is included in recall. Use Recall Preview on an elliptical follow-up and confirm the displayed retrieval query includes the preceding user topic.
5. Create several explicit, related memories across at least two conversations. Run consolidation. Confirm the generated summary remains pending review and exposes all supporting source records.
6. Accept the summary, confirm it can be recalled, then edit one source record. Confirm the dependent summary becomes disputed and is excluded from present-focused retrieval while remaining available to historical inspection.
7. Restart V and confirm the timeline, commitment state, and accepted derivation persist.

The automated suite covers backup/restore, schema migration, and model-change reindexing. Do not test restore against the only live memory database; use a disposable database if performing a manual restore test.


## 12. Acceptance criteria

Phase 2 is verified only when all of the following hold:

- [x] Existing memory data, evidence links, relationships, temporal records, commitments, and semantic embeddings survive supported schema migrations.
- [x] Memory records retain their provenance and source-message references; derived summaries retain explicit links to every source.
- [x] Temporal states distinguish current, superseded, corrected, disputed, and expired information. Current-focused recall excludes invalidated records while historical recall can still inspect them.
- [x] Consolidation is evidence-backed, avoids duplicate output, detects contradictions, requires review before derived records become current recall sources, and invalidates accepted derivations when their source evidence changes.
- [x] Explicit future commitments can be extracted, inspected, corrected, completed, cancelled, and selectively recalled with source quotations. They do not silently schedule notifications or authorize actions.
- [x] Retrieval prioritizes direct current matches, resolves contextual follow-ups, respects a bounded context budget, and falls back safely when semantic retrieval is unavailable.
- [x] The desktop UI exposes memory inspection, chronological timelines, temporal editing, derivation review, commitment management, deletion, backup/restore, and an exact recall-context preview.
- [x] Background memory work is bounded and cancellable; interactive chat takes priority. Retrieval and memory processing remain local and do not send private content to web search or cloud LLM providers.
- [x] Automated tests cover multiple conversations and sessions, restart persistence, temporal recall, derivation invalidation, backup/restore, schema migration, and embedding-model changes.
- [ ] The configured local chat and embedding models pass the target-PC evaluation and desktop smoke-test checklist in Section 11 without a cloud fallback or resource failure.

The first nine criteria are implemented and covered by the passing Windows CI run. The final target-PC criterion remains open; Phase 2 must stay In progress until the local-model/GPU smoke test passes.

## 13. Explicitly out of scope

Identity definition/evolution (Phase 1), full appraisal/affect/motivation/reflection (Phase 3), new sensor/vision capabilities (Phase 4), and autonomous initiative/background projects (Phase 5).
