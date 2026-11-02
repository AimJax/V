# V Long-Term Memory

## Database

`G:/V/data/memory/memory.sqlite3`

SQLite stores memory records, the extraction queue, and semantic embedding metadata and vectors.

## Current implementation

- Automatic extraction of durable information from user-authored messages.
- Historical reprocessing of every stored user message, including messages whose original extraction job was already completed.
- Durable review proposals that can be approved, edited, rejected, or marked as duplicate without changing existing memories.
- Automatic extraction key conflicts are retained as separate review proposals with a snapshot of the existing record; reviewers can reject them or save the new statement under a different key without overwriting the existing memory.
- Resumable backfill checkpoints and per-run processing statistics stored in the memory database.
- Original source timestamps and limited adjacent-conversation context are retained for historically accurate review; evidence still comes only from the quoted source user message.
- Explicit-only extraction; inferred patterns are not automatically stored.
- Verbatim evidence excerpts are stored instead of model-generated paraphrases.
- Background extraction after a configurable idle period.
- SQLite FTS5 lexical search.
- Local semantic retrieval using Nomic embeddings through LM Studio.
- A versioned relationship graph connects memories by exact canonical subject, shared original source message, or identical episodic timeline key. These are structural associations, not model-invented causal claims.
- Inferred patterns have a separate many-to-many evidence ledger: they must be supported by at least three explicit memories from three distinct source messages across at least two conversations.
- Correcting a source statement invalidates derived patterns that depend on it. Deleting evidence removes a pattern if the remaining evidence no longer meets the minimum threshold.
- Version 3 JSON backups preserve inferred-pattern evidence links; version 1 and 2 backups remain importable.
- Retrieval can add one-hop associated memories when direct results leave room, preserving direct query matches first.
- Existing memories are linked during schema migration; new records and subject/key corrections refresh their relationships automatically.
- Bounded memory context injected into the conversation system message.
- Memory listing, searching, status inspection, correction, and deletion through chat commands.
- Versioned JSON export and validated, transactional merge restore through the CLI.

## Memory fields

- Type: profile, preference, episodic, relationship, project, fact, inferred_pattern.
- Subject and human-readable content.
- Optional normalized, unique memory key.
- Provenance: explicit or inferred.
- Confidence from 0.0 to 1.0.
- Importance from 1 to 5.
- Source conversation ID and source message ID.
- Optional supporting evidence.
- Creation, modification, and last-confirmation timestamps. Explicit confirmation updates only `last_confirmed_at`; original source timestamps and evidence remain unchanged.

## Chat commands

- `/memory` — list saved memories.
- `/memory search TEXT` — search saved memories.
- `/memory status` — inspect saved-memory and extraction-queue status.
- `/memory correct ID FIELD VALUE` — correct one field on a saved memory.
- `/memory confirm ID` — explicitly confirm a saved memory is still true without changing its original source date or evidence.
- `python -m v memory confirm ID` — perform the same confirmation from PowerShell.
- `/memory delete ID` — permanently delete a memory.
- `/memory retry` — retry failed automatic extraction jobs.
- `python -m v memory backfill` — reprocess historical user messages into a review queue.
- `python -m v memory backfill --status` — inspect the latest backfill run.
- `python -m v memory review list` — inspect pending historical proposals.

Correction fields: `content`, `subject`, `type`, `key`, `confidence`, `importance`, and `evidence`. Quote values containing spaces. Use `--clear` to clear an optional `key` or `evidence`. Corrections preserve the original creation timestamp and source conversation/message references.

## Export and restore

Export all memories:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory export "G:/V/backups/memories.json"
```

Replace an existing export only when explicitly requested:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory export "G:/V/backups/memories.json" --overwrite
```

Restore from a backup:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory import "G:/V/backups/memories.json"
```

Restore uses merge semantics. Identical existing memory IDs are skipped. A conflicting ID or unique memory key aborts the entire import; existing records are never overwritten or deleted. The import retains memory IDs, provenance, source references, evidence, and timestamps. It does not restore conversation history, extraction jobs, or embedding vectors. Missing or stale semantic vectors are rebuilt locally when retrieval next needs them.

The backup format is versioned JSON. Import validates the format, version, field set, record values, timestamps, duplicate IDs, and duplicate keys before writing. A failed import rolls back the complete batch.

## Privacy and limitations

- Memory is stored locally in SQLite and is not encrypted by this implementation.
- JSON exports are also unencrypted and may contain personal data. Store them in a protected location.
- The database, WAL files, and backups must never be committed to Git.
- Deleting a memory removes its database row and FTS index entry. It does not erase copies in conversation history or external backups; those are separate data sources.
- Historical messages are never automatically accepted as new memories: backfill proposals require explicit review.
- Memories are not automatically expired or deleted. An explicit confirmation records when the user last reaffirmed a memory; missing confirmation does not mean the memory is false.
- Automatic inferred-pattern extraction is disabled.
- Automatic key conflicts are reviewable, but automatic consolidation and in-place replacement are intentionally not implemented. A reviewer must choose a distinct key to retain both statements; existing memories are never overwritten by conflict approval.
- The Memory Manager includes historical scan controls and an editable proposal-review window. The CLI remains available for scripted or headless use.
- Database encryption is not implemented.
