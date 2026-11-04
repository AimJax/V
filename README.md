# V

V is a local-first AI companion for Windows. Implemented capabilities currently include local text conversation, persistent conversation history, automatic explicit-memory extraction, and hybrid memory retrieval. Voice, vision, file inspection, autonomous initiative, and the desktop environment remain planned capabilities.

## Hardware target
- Windows 10 22H2
- Intel Core i7-4770K
- NVIDIA RTX 2060 Super, 8 GB VRAM
- 32 GB system RAM
- Dedicated 128 GB SSD for V-owned models, data, caches, logs, recordings, and projects

The user has confirmed that the selected Qwen3.5 4B uncensored GGUF model runs quickly, fits fully in VRAM, and supports an 8K context on this machine. Re-benchmark only when changing model, quantization, runtime, context size, or adding concurrent specialist models.

## Local inference
V uses a local OpenAI-compatible inference API. LM Studio is the default backend. Application logic uses a provider factory and protocol rather than depending directly on LM Studio internals. A compatible llama.cpp server can be selected explicitly using a loopback endpoint.

The initial model target is **HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive**. The model identifier in `config/default.toml` must exactly match the identifier exposed by the local server. If it differs, override `llm.model` in the untracked `config/local.toml`. V must never silently select a different model or use a cloud fallback.

## Current technology
- Python 3.13
- HTTPX for asynchronous local API communication
- SQLite for persistent conversations, memory, and extraction jobs
- SQLite FTS5 and optional local embeddings for hybrid memory retrieval
- PySide6 planned for the desktop interface

## Privacy
Private AI inference and private-data processing must remain local. Cloud AI fallback and hidden telemetry are prohibited. Internet search is separately configurable; it must never receive complete private conversations, private memories, local files, or camera images.

## Project structure
- `src/v/` — application source
- `config/` — default configuration and local overrides
- `data/` — private application data
- `models/` — local AI models
- `cache/` — application caches
- `tests/` — automated tests
- `docs/` — technical documentation

## Development
Use the isolated Python environment:

`G:\V\.venv\Scripts\python.exe`

Start a conversation: `python -m v chat`

Run diagnostics: `python -m v doctor`

Run tests: `python -m pytest`

See `AGENTS.md`, `docs/V_Principles.md`, and `docs/V_Technical_Principles.md` for persistent requirements.
