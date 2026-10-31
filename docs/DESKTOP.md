# V Desktop Application

## Initial desktop milestone

The first desktop interface is a native Qt Widgets application built with the official PySide6 bindings.

- The Qt interface runs on the main GUI thread.
- The async inference, conversation persistence, semantic retrieval, and memory extraction runtime runs in a dedicated QThread with its own asyncio event loop.
- Chat uses the configured LM Studio model and the same local conversation and memory databases as the CLI.
- Conversation history is restored from SQLite and can be switched from the recent-session list.
- The Memory Manager searches and filters records by content, memory type, and provenance.
- Memory content, subject, type, key, confidence, importance, and supporting evidence can be corrected while original source references are retained.
- Permanent memory deletion requires confirmation and explicitly notes that conversation-history and backup copies are separate.
- Memory JSON export and merge-only import are available from the manager, with plaintext and overwrite warnings.
- Memory database operations are routed through the runtime thread rather than the Qt GUI thread.
- The desktop service does not start cloud inference, telemetry, or external error reporting.
- The CLI remains available independently of the optional desktop dependency.

## Install and launch

From PowerShell:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m pip install -e ".[desktop]"
& "G:/V/.venv/Scripts/python.exe" -m v desktop
```

LM Studio must be running with the configured model loaded before V starts. The GUI reports a local connection error instead of choosing another provider or model.

## Qt / Windows compatibility

The optional dependency is constrained to `PySide6>=6.11,<6.13`. Qt 6.12 is the final Qt release line supporting Windows 10; Windows 10 22H2 is within the documented Windows 10 1809-or-later support range. This upper bound prevents a future Qt 6.13 upgrade from silently dropping the target OS.

## Current scope

This is the first graphical milestone, not the complete planned application. It currently provides persistent local chat, streaming responses, recent conversation switching, local model status, and background memory extraction/retrieval.

Voice controls, wake-word configuration, webcam/vision, a dedicated memory manager, editable settings screens, tray/background controls, packaging, and installer work remain future stages.
