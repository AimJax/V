"""Command-line entry point for V."""

from __future__ import annotations

import argparse
import asyncio
import sys

from v.chat import run_chat
from v.diagnostics import main as run_diagnostics


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

    args = parser.parse_args()

    try:
        if args.command == "chat":
            return asyncio.run(run_chat())

        if args.command == "doctor":
            run_diagnostics()
            return 0

        parser.print_help()
        return 0

    except KeyboardInterrupt:
        print("\nV stopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())