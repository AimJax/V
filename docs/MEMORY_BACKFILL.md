# Historical Memory Backfill and Review

## Purpose

Normal extraction only processes user messages placed in the automatic extraction queue. Earlier messages may already be marked completed under older extraction rules. Historical backfill scans the persistent conversation database independently, so those messages can be evaluated again without resetting or rewriting the automatic queue.

Backfill is deliberately a proposal workflow. It never inserts proposed memories into the active memory table until a person approves them.

## What it scans

- Every stored user-authored message in every saved conversation.
- Messages are read in ascending permanent message-ID order, in bounded pages.
- Each source user message is accompanied by at most one neighboring message before and after it, capped at 1,200 characters each, to clarify references without expanding the evidence source.
- The original source timestamp is retained in each proposal and shown in review so old circumstances remain historically dated.
- The scan records an upper message-ID boundary when a run starts. Messages added after that boundary belong to normal ongoing extraction and are not mixed into the current historical run.
- Assistant messages are never sent as source material.
- The same explicit-evidence, confidence, and sensitive-information validation used by normal extraction is applied.
- Existing memory records and automatic extraction queue states are not reset, overwritten, or deleted.

Each accepted proposal retains the source conversation ID, source message ID, exact supporting quotation, model-suggested summary, memory type, proposed key, confidence, and importance.

## Run a backfill

From PowerShell in `G:\V`:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory backfill
```

The command uses the configured chat model through the local LM Studio endpoint. It does not use cloud inference or send conversation data to an external service.

Default batch size is five user messages. Use a smaller batch if individual messages are unusually long or the local model has a limited context window:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory backfill --batch-size 1
```

Progress is printed after each committed batch. The run records its cursor, processed count, proposal count, skipped-candidate count, status, and most recent error in the memory database.

Inspect the latest run without contacting LM Studio:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory backfill --status
```

## Resume and repeat

If V closes or a run is interrupted, its last committed checkpoint is retained. On the next backfill invocation, an incomplete run is resumed automatically. If interruption occurs during a model request, that batch is retried from its previous checkpoint; candidates from earlier committed batches remain intact.

A completed run is not silently repeated. To deliberately scan the entire current history again with the current extraction rules, start a new run:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory backfill --new-run
```

Runs and their proposal history are retained. New runs do not erase previous approvals, rejections, or review records.

## Desktop workflow

Open **Memory Manager → Reprocess history…**. The window shows the latest scan checkpoint, processed-message count, proposal count, and skipped-candidate count.

**Start / Resume scan** creates a first scan or resumes an interrupted one. **Pause** stops after the current committed batch. **New full scan…** explicitly creates a new run over the historical message snapshot; previous runs, review decisions, and active memories remain intact.

The proposal list can be filtered by pending, approved, rejected, duplicate, or all. Selecting a pending proposal shows the exact source evidence and the model-suggested summary separately. You can edit the memory type, subject, content, unique key, confidence, and importance before approving it. Rejection is confirmed and retained with an optional reason. Accepted records become normal searchable/retrievable memories.

Chat and voice turns take priority over backfill. A new turn pauses the scan at its last committed batch; it does not delay the conversation.

The desktop controls run through V's runtime thread. SQLite and local-model calls do not execute on the Qt GUI thread.

## Review proposals

List pending proposals:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory review list
```

Each proposal displays its ID, type, subject, suggested summary, exact evidence quotation, proposed memory key, confidence, importance, and source message ID.

Approve a proposal:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory review approve CANDIDATE_ID
```

By default, approved memory content is the exact evidence excerpt, matching the current automatic-extraction policy. The model-suggested summary is shown for review but is not silently substituted for the source quotation.

Edits may be supplied when approving:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory review approve CANDIDATE_ID --content "The user currently works in construction." --memory-type episodic --subject "Current work context" --memory-key "user.current_work_context" --importance 4
```

Reject a proposal and preserve the decision record:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory review reject CANDIDATE_ID --reason "Temporary or no longer useful"
```

Inspect other review outcomes:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m v memory review list --status approved
& "G:/V/.venv/Scripts/python.exe" -m v memory review list --status rejected
& "G:/V/.venv/Scripts/python.exe" -m v memory review list --status duplicate
& "G:/V/.venv/Scripts/python.exe" -m v memory review list --status all
```

## Duplicate and conflict handling

- Approving a proposal never overwrites an existing memory.
- Memory keys are unique. If a proposal conflicts with a key already in use, it is retained with status `duplicate` and a reference to the existing memory.
- If a process stops after creating a memory but before recording the approval, retrying the same proposal recognizes the matching source and evidence rather than creating a second memory.
- Rejected and duplicate proposals remain in the review database for auditability.
- A user can edit a pending proposal before approval. The original source quotation and source references remain unchanged.

## Storage and privacy

Backfill run records, candidate payloads, decision notes, and checkpoints are stored locally in the same SQLite database as long-term memories. Conversation source text remains in the conversation database; proposal records retain only validated excerpts and their metadata, not a second copy of every conversation.

This intentionally retains historical review records and does not apply an automatic retention limit. It increases local storage use over time. Storage is not encrypted by this implementation; protect the V data directory and keep unencrypted backups in a location you control.

Backfill does not alter conversation history, delete existing memories, or reset automatic extraction queue records.
