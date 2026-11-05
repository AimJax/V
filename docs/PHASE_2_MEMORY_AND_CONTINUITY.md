# Phase 2 — Memory and Continuity

**Status:** Planned  
**Objective:** Evolve the existing memory implementation into coherent, time-aware autobiographical continuity without replacing working infrastructure or weakening evidence quality.

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

A time-ordered account of significant experiences and developments relevant to V's identity and relationship context. This is a derived navigation layer over evidence-backed memories, not a fictional biography.

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

1. Inventory memory schemas, extraction, retrieval, graph, backup, UI, and tests.
2. Define canonical semantics for episodic, semantic, procedural, prospective, and derived autobiographical records.
3. Add only necessary schema extensions with versioned migrations.
4. Implement temporal validity and supersession rules.
5. Implement evidence-linked consolidation and invalidation.
6. Improve contextual retrieval and bounded context assembly.
7. Extend desktop inspection, correction, merge, and lifecycle controls.
8. Add realistic multi-conversation, multi-session continuity evaluations.

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

## 11. Acceptance criteria

Phase 2 is verified when V maintains useful, evidence-linked, time-aware continuity across sessions; recalls relevant context naturally; distinguishes event, fact, inference, and summary; and lets the user inspect, correct, export, and delete memory without corruption.

## 12. Explicitly out of scope

Identity definition/evolution (Phase 1), full appraisal/affect/motivation/reflection (Phase 3), new sensor/vision capabilities (Phase 4), and autonomous initiative/background projects (Phase 5).
