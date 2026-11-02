# Automatic Memory Extraction

## Current implementation

- User messages are queued after successful assistant responses.
- Extraction begins after a configurable idle period.
- The background worker is cancellable when a new user message arrives.
- Cancelled work remains pending for a later attempt.
- Pending jobs survive application restarts.
- Failed jobs remain retryable, with a maximum of three attempts before failure.
- The worker processes a configurable number of extraction batches per idle cycle.
- Each normal worker extraction call processes up to five user messages.
- Automatic extraction and historical backfill use the same candidate validation rules.
- Only user-authored messages belonging to the queued conversation are accepted.
- Each user message is evaluated with at most one adjacent message before and after it for reference and chronology context.
- Adjacent messages can clarify intent but are never accepted as evidence; evidence must be an exact quote from the specific source user message.
- Original message timestamps accompany extraction so historical statements are not mistaken for present-day facts.
- Memories require an exact source quotation.
- Subject labels are canonicalized by the local extraction prompt so memories about the same named project or entity can be grouped consistently.
- Evidence matching is whitespace-normalized and case-insensitive.
- The stored memory content is the verbatim evidence excerpt, not an LLM-generated paraphrase.
- Only explicit statements are accepted in this initial version.
- Candidates below the configured confidence threshold are rejected.
- Sensitive candidates are rejected.
- Duplicate memory keys cannot silently overwrite existing memories.
- A new non-episodic statement that reuses an occupied key is saved as a durable conflict proposal. The current memory is snapshotted into the proposal and remains unchanged until the user reviews it.

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

- Existing historical conversations are not automatically accepted into memory. Use the separate historical backfill workflow to scan them into a review queue.
- Inferred pattern extraction is intentionally disabled.
- Automatic key-conflict proposals appear alongside historical backfill proposals in the same Memory Review window and CLI review list. Approval requires assigning a different unique key; approval never overwrites the conflicting record.
- Historical proposals must be explicitly approved or rejected. Approval can include user edits; rejection records remain available for audit.
- Semantic retrieval is implemented separately and uses local Nomic embeddings with FTS5 fallback.
- Data is stored locally in SQLite without database encryption.
- There is no graphical memory manager or export/restore workflow.
