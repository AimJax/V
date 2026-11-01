# Memory Retrieval

V retrieves relevant saved memories for each user turn.

## Hybrid retrieval
- Local Nomic embeddings provide semantic similarity.
- SQLite FTS5 provides lexical matching and offline fallback.
- Nomic uses separate document and query prefixes.
- Initial semantic relevance threshold: 0.60.
- Exact keyword matches can provide a small ranking adjustment.
- At most five memories are included by default.
- Memory context is capped at 2,400 characters.
- Context distinguishes original source dates from explicit user-confirmation timestamps. Unconfirmed memories remain available but are not treated as freshly confirmed.

## Local retrieval evaluation

Run a threshold sweep using the configured local embedding model:

```powershell
& ".\.venv\Scripts\python.exe" -m v memory evaluate
```

The benchmark creates a temporary SQLite database under `tmp/memory-evaluation` and embeds a fictional corpus and its queries through the local embedding endpoint. It compares several semantic thresholds, including the currently configured value, against an FTS5-only baseline. It reports precision, recall, mean reciprocal rank, and false-positive rate on no-answer queries. The temporary database is removed after the run. The configured memory database is never read or modified, and no threshold is applied automatically. This synthetic benchmark is a calibration aid, not a substitute for a separately curated evaluation set based on real retrieval needs.

## Integration
- Retrieval occurs before the chat completion request.
- Personality and retrieved memories are combined into one system message.
- Conversation history remains separate.
- A failure in memory retrieval must not prevent a normal conversation.
- User messages cancel idle-time extraction before new generation begins.

## Privacy
All embeddings and retrieval are local.
No conversation text or memory is sent to a third-party embedding service.

## Limitations
- The threshold remains configurable; use repeated local evaluation before changing it. The included fictional benchmark is a calibration aid, not a personalized ground-truth set.
- The current index is rebuilt lazily when missing or stale embeddings are found.
- FTS5 fallback is lexical, not semantic.
- There is no automatic historical conversation import.