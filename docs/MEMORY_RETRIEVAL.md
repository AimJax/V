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

The benchmark creates a temporary SQLite database under `tmp/memory-evaluation` and embeds a fictional corpus and its queries through the local embedding endpoint. It compares semantic thresholds against an FTS5-only baseline and reports precision, recall, MRR, and no-answer false-positive rate. The temporary database is removed after the run. The configured memory database is never read or modified, and no threshold is applied automatically. This is a calibration aid, not a personalized ground-truth set.

## Personalized retrieval evaluation

Create a private starter file:

```powershell
& ".\.venv\Scripts\python.exe" -m v memory eval-init
```

Edit `data/memory/evaluation_cases.json`. Add realistic questions to its `cases` array and label the full memory IDs that should answer each question. Find IDs with `/memory search TEXT` in chat or in the desktop Memory Manager. Use an empty `relevant_memory_ids` array for a question that should retrieve nothing. Include at least one answerable case and one no-answer case. For historical questions, label the dated snapshots that answer them; for current questions, label the latest relevant snapshot.

Run the personalized evaluation:

```powershell
& ".\.venv\Scripts\python.exe" -m v memory evaluate --personal
```

Use `--cases data/memory/another_set.json` to select another local label file. The benchmark validates every labeled ID against the current database and reports stale IDs instead of silently ignoring them. It reports per-question hits and misses, context size, and threshold-level precision, recall, MRR, and no-answer false-positive rate.

Personal mode opens the memory database and compatible embedding cache read-only. Missing or stale vectors are embedded in bounded batches through the configured loopback LM Studio endpoint and held only in RAM. No memory rows or cached vectors are written. The label file may contain sensitive questions and IDs, so keep it in V's ignored `data/` directory. Do not commit or share it.

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