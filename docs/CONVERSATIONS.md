# Persistent Conversations

V stores completed conversation exchanges in a local SQLite database.

## Location

`G:\V\data\conversations\conversations.sqlite3`

SQLite may also create temporary WAL and shared-memory files beside the database.
Those files are part of the same local storage system.

## Behavior

- V automatically opens the most recently updated conversation on startup.
- `/new` starts another conversation without deleting previous sessions.
- `/sessions` lists recent conversations.
- `/resume N` opens a conversation from that list.
- The first user message becomes the conversation title.
- All completed exchanges are retained in SQLite.
- Only the most recent configured messages are sent to the model as context.
- An interrupted or failed generation is not saved as a completed exchange.

## Privacy

Conversation contents are stored locally as ordinary SQLite data.
They are not encrypted by this initial implementation.
Do not put the database in GitHub or share it unintentionally.

This database is conversation history, not the future long-term memory system.
The memory system will separately extract, index, and manage useful information.