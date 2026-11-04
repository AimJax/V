# V Long-Term Memory

## Database
`G:\V\data\memory\memory.sqlite3`

## Current implementation
The memory subsystem is a local SQLite-backed subsystem. It currently provides:

- Memory creation, inspection, listing, keyword search, correction, and permanent deletion.
- Explicit and inferred provenance fields, confidence, importance, evidence, and source-message references.
- Automatic extraction of explicit memories from queued user messages after a configurable idle period.
- A cancellable background extraction worker with retryable failed jobs.
- Hybrid retrieval using SQLite FTS5 and optional local Nomic embeddings.
- Lazy embedding indexing, relevance ranking, and lexical fallback when the embedding API is unavailable.
- Injection of a bounded selection of relevant memories into the system context before generation.

See `MEMORY_EXTRACTION.md` and `MEMORY_RETRIEVAL.md` for detailed behavior.

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

## Privacy and deletion
Memory is stored locally in SQLite and is not encrypted by this implementation. The database, WAL files, and backups must never be committed to Git.

Deleting a memory removes its database row and FTS index entry. Its associated embedding is also removed by the memory deletion path. This does not automatically erase the source conversation, previously generated summaries, exported copies, or independent backups. Those remain separate data sources and require a source-aware deletion workflow.

## Known limitations
- Automatic extraction currently favors explicit statements with exact source quotations; it is not yet the richer autobiographical, affective, procedural, or prospective memory architecture described in the technical principles.
- Inferred pattern extraction and memory consolidation/conflict resolution are not implemented.
- Historical conversations are not automatically imported into memory.
- Semantic retrieval requires a separately loaded local embedding model and currently uses the configured local OpenAI-compatible embedding endpoint.
- Memory correction and export/restore are not exposed through a user-facing memory manager.
- Database encryption and comprehensive derived-data deletion are not implemented.
- The current retrieval index lazily embeds records and has not been benchmarked for large memory collections.
