# V Long-Term Memory

## Database
`G:\V\data\memory\memory.sqlite3`

## Current scope
This subsystem currently provides local storage and retrieval primitives.
It does not yet perform automatic extraction or inject memories into prompts.

## Memory fields
- Type: profile, preference, episodic, relationship, project, fact, inferred_pattern.
- Subject and human-readable content.
- Optional normalized memory key.
- Provenance: explicit or inferred.
- Confidence from 0.0 to 1.0.
- Importance from 1 to 5.
- Source conversation ID and source message ID.
- Optional supporting evidence.
- Creation, modification, and last-confirmation timestamps.

## Operations
- Create, inspect, list, and search memories.
- Filter by type or provenance.
- Correct memory fields while preserving original source references.
- Permanently delete memories.
- Rebuild/optimize the FTS5 search index.

## Privacy
Memory is stored locally in SQLite.
It is not encrypted by this initial implementation.
The database, WAL files, and backups must never be committed to Git.

Deleting a memory removes its database row and FTS index entry. It does not
automatically erase copies that may exist in conversation history or external
backups. Those are separate data sources and must be handled independently.

## Not implemented yet
- Automatic memory extraction.
- Memory consolidation and conflict resolution.
- Semantic embedding retrieval.
- Memory relevance ranking for chat prompts.
- User-facing memory manager and export/restore interface.