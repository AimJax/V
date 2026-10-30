# Automatic Memory Extraction

## Current implementation
- User messages are queued after successful assistant responses.
- Extraction begins after a configurable idle period.
- The worker is cancellable when a new user message arrives.
- Cancelled work remains pending for a later attempt.
- Failed jobs remain retryable.
- Each extraction request processes one user message at a time.
- Only user-authored messages belonging to the queued conversation are accepted.
- Memories require an exact source quotation.
- The stored memory content is the verbatim evidence excerpt, not an
  LLM-generated paraphrase.
- Only explicit statements are accepted in this initial version.
- Low-confidence and sensitive candidates are rejected.
- Duplicate memory keys cannot silently overwrite existing memories.

## Commands
- `/memory` lists saved memories.
- `/memory search TEXT` searches saved memories.
- `/memory status` shows saved memory and queue counts.
- `/memory delete ID` permanently deletes a memory.
- `/memory retry` resets failed extraction jobs.

## Timing
Default idle delay: 20 seconds.
Default maximum jobs per idle cycle: 3.

## Limitations
- Existing historical conversations are not automatically imported.
- Semantic embedding retrieval is not yet integrated.
- Inferred pattern extraction is intentionally disabled.
- Memory correction is available through the storage API but not yet exposed
  as a conversational command.
- Data is stored locally in SQLite without database encryption.