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

Run the personalized benchmark directly:

```powershell
& ".\.venv\Scripts\python.exe" -m v memory evaluate --personal
```

No JSON file or manual labeling is required. V opens its configured memory database read-only, selects up to 40 high-value memories while preferring subject diversity, and asks the configured local chat model to generate one natural retrieval question per selected memory. Each question is linked in code to its source memory ID; the model generates question wording but does not decide the expected memory IDs. Questions are generated in bounded batches and kept in RAM only.

The generated questions and memory contents are sent only to the local endpoint authorized by V's network policy. The evaluator then uses the configured local embedding model to compare thresholds. Existing cached vectors are read without writes; missing or stale vectors are created in RAM. Neither the memory database nor embedding cache is modified, and no evaluation file is written.

This automatic set is a source-anchored calibration sample, not a human-verified ground-truth benchmark. Since it contains answerable questions only, no-answer rejection is shown as `n/a`; use the separate synthetic benchmark for a measured no-answer false-positive rate.

For an optional manually curated evaluation, use `--cases data/memory/your_cases.json` with `--personal`. The `memory eval-init` command creates a private starter file for this advanced workflow. Manual no-answer cases are optional. Keep such files under V's ignored `data/` directory and do not commit or share them.

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