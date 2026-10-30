# Automatic Memory Extraction

## Current implementation

- User messages are queued after successful assistant responses.
- Extraction begins after a configurable idle period.
- The background worker is cancellable when a new user message arrives.
- Cancelled work remains pending for a later attempt.
- Pending jobs survive application restarts.
- Failed jobs remain retryable, with a maximum of three attempts before failure.
- The worker processes a configurable number of jobs per idle cycle.
- Each normal worker extraction call processes one user message.
- Only user-authored messages belonging to the queued conversation are accepted.
- Memories require an exact source quotation.
- Evidence matching is whitespace-normalized and case-insensitive.
- The stored memory content is the verbatim evidence excerpt, not an LLM-generated paraphrase.
- Only explicit statements are accepted in this initial version.
- Candidates below the configured confidence threshold are rejected.
- Sensitive candidates are rejected.
- Duplicate memory keys cannot silently overwrite existing memories.

## Commands

- `/memory` lists saved memories.
- `/memory search TEXT` searches saved memories.
- `/memory status` shows saved memory and queue counts, worker state, the latest extraction report, and recent failed-job errors.
- `/memory delete ID` permanently deletes a memory.
- `/memory retry` resets failed extraction jobs.

## Timing

Default idle delay: 20 seconds.

Default maximum jobs per idle cycle: 3.

Default minimum extraction confidence: 0.90.

## Limitations

- Existing historical conversations are not automatically imported.
- Inferred pattern extraction is intentionally disabled.
- Memory correction is available through the storage API but not exposed as a conversational command.
- Semantic retrieval is implemented separately and uses local Nomic embeddings with FTS5 fallback.
- Data is stored locally in SQLite without database encryption.
- There is no graphical memory manager or export/restore workflow.
