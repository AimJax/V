# V Long-Term Memory

## Database

`G:\V\data\memory\memory.sqlite3`

SQLite stores memory records, the extraction queue, and semantic embedding metadata and vectors.

## Current implementation

- Automatic extraction of durable information from user-authored messages.
- Explicit-only extraction; inferred patterns are not automatically stored.
- Verbatim evidence excerpts are stored instead of model-generated paraphrases.
- Background extraction after a configurable idle period.
- SQLite FTS5 lexical search.
- Local semantic retrieval using Nomic embeddings through LM Studio.
- Bounded memory context injected into the conversation system message.
- Memory listing, searching, status inspection, and deletion through CLI commands.

## Memory fields

- Type: profile, preference, episodic, relationship, project, fact, inferred_pattern.
- Subject and human-readable content.
- Optional normalized, unique memory key.
- Provenance: explicit or inferred.
- Confidence from 0.0 to 1.0.
- Importance from 1 to 5.
- Source conversation ID and source message ID.
- Optional supporting evidence.
- Creation, modification, and last-confirmation timestamps.

## Operations

The storage API supports:
- Create, inspect, list, and search memories.
- Filter by type or provenance.
- Correct memory fields while preserving original source references.
- Permanently delete memories.
- Rebuild or optimize the FTS5 search index.

CLI commands:
- `/memory` ? list memories.
- `/memory search TEXT` ? search memories.
- `/memory status` ? inspect memory and extraction queue status.
- `/memory delete ID` ? permanently delete a memory.
- `/memory retry` ? retry failed extraction jobs.

## Privacy

Memory is stored locally in SQLite and is not encrypted by this implementation.

The database, WAL files, and backups must never be committed to Git.

Deleting a memory removes its database row and FTS index entry. It does not automatically erase copies that may exist in conversation history or external backups. Those are separate data sources and must be handled independently.

## Limitations

- Existing historical conversations are not automatically imported.
- Automatic inferred-pattern extraction is disabled.
- Memory consolidation and conflict resolution are not implemented.
- Memory correction is available through the storage API but not yet exposed as a CLI command.
- Export and restore workflows are not implemented.
- A graphical memory manager is not implemented.
- Database encryption is not implemented.
