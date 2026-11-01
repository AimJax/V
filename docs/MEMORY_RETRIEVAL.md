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
- The threshold is provisional and based on a small initial benchmark.
- The current index is rebuilt lazily when missing or stale embeddings are found.
- FTS5 fallback is lexical, not semantic.
- There is no automatic historical conversation import.