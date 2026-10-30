# V

V is a local-first AI companion for Windows.

## Target hardware
- Windows 10 22H2
- Intel Core i7-4770K
- NVIDIA RTX 2060 Super 8 GB
- 32 GB RAM

## Initial technology choices
- Python 3.13
- LM Studio local inference API
- HTTPX for asynchronous HTTP communication
- PySide6 planned for the desktop interface
- SQLite for persistent conversations and future memory storage

These choices will be validated during implementation and benchmarking.

## Privacy
AI inference and private-data processing must remain local.
Cloud AI fallback and hidden telemetry are prohibited.
Internet search is an explicitly configurable exception.

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

Start a conversation:

`python -m v chat`

Run diagnostics:

`python -m v doctor`

See `AGENTS.md` for persistent development requirements.