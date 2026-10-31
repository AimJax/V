"""Command-line entry point for V."""

from __future__ import annotations

import argparse
import asyncio
import sys

from pathlib import Path

from v.chat import run_chat
from v.core.config import load_settings, project_root
from v.diagnostics import main as run_diagnostics
from v.memory.backup import export_backup, import_backup
from v.memory.store import MemoryStore


def _memory_store() -> MemoryStore:
    settings = load_settings()
    root = project_root().resolve()
    configured = Path(settings["paths"]["memory_db"])
    database_path = (
        configured if configured.is_absolute() else root / configured
    ).resolve()

    if not database_path.is_relative_to(root):
        raise ValueError("Configured memory database must remain inside V_HOME.")

    return MemoryStore(database_path)


def _run_memory_export(destination: str, *, overwrite: bool) -> int:
    path, count = export_backup(
        _memory_store(),
        destination,
        overwrite=overwrite,
    )
    print(f"Exported {count} memory record(s) to: {path}")
    print("Privacy: this JSON backup is unencrypted and may contain personal data.")
    return 0


def _run_memory_import(source: str) -> int:
    restored, skipped = import_backup(_memory_store(), source)
    print(f"Restored: {restored} memory record(s)")
    print(f"Skipped identical records: {skipped}")
    print("Import mode: merge; existing memories are never overwritten or deleted.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="v",
        description="V — Local AI Companion",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "chat",
        help="Start an interactive conversation with V.",
    )

    subparsers.add_parser(
        "doctor",
        help="Check the local AI runtime connection.",
    )

    subparsers.add_parser(
        "desktop",
        help="Open V's Windows desktop application.",
    )

    memory_parser = subparsers.add_parser(
        "memory",
        help="Export or restore long-term memories.",
    )
    memory_actions = memory_parser.add_subparsers(dest="memory_action")

    export_parser = memory_actions.add_parser(
        "export",
        help="Export memories to a versioned JSON backup.",
    )
    export_parser.add_argument("destination", help="Destination JSON file path.")
    export_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing destination file.",
    )

    import_parser = memory_actions.add_parser(
        "import",
        help="Restore memories from a JSON backup using merge semantics.",
    )
    import_parser.add_argument("source", help="Source JSON backup file path.")

    args = parser.parse_args()

    try:
        if args.command == "chat":
            return asyncio.run(run_chat())

        if args.command == "doctor":
            return run_diagnostics()

        if args.command == "desktop":
            try:
                from v.desktop.app import main as run_desktop
            except ImportError as error:
                print(
                    "Desktop dependencies are not installed. "
                    'Run: python -m pip install -e ".[desktop]"',
                    file=sys.stderr,
                )
                print(f"Import detail: {error}", file=sys.stderr)
                return 1
            return run_desktop()

        if args.command == "memory":
            if args.memory_action == "export":
                return _run_memory_export(
                    args.destination,
                    overwrite=args.overwrite,
                )

            if args.memory_action == "import":
                return _run_memory_import(args.source)

            memory_parser.print_help()
            return 0

        parser.print_help()
        return 0

    except KeyboardInterrupt:
        print("\nV stopped.")
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"V operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
