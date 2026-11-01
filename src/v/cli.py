"""Command-line entry point for V."""

from __future__ import annotations

import argparse
import asyncio
import sys

from pathlib import Path

from v.chat import run_chat
from v.core.config import load_settings, project_root
from v.core.network import NetworkPolicy
from v.conversations.store import ConversationStore
from v.diagnostics import main as run_diagnostics
from v.memory.backup import export_backup, import_backup
from v.memory.backfill import (
    MemoryBackfillRunner,
    MemoryBackfillStore,
    MemoryReviewService,
)
from v.memory.extractor import MemoryExtractor
from v.memory.queue import ExtractionQueue
from v.memory.store import MemoryStore
from v.providers.lm_studio import LMStudioProvider


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


def _run_memory_confirm(memory_id: str) -> int:
    memory = _memory_store().confirm_memory(memory_id)
    print(f"Confirmed memory: {memory.id}")
    print(f"Last confirmed: {memory.last_confirmed_at}")
    print(f"Original source date: {memory.source_created_at or 'unknown'}")
    print("Original evidence, source references, and memory content were preserved.")
    return 0


def _conversation_store() -> ConversationStore:
    settings = load_settings()
    root = project_root().resolve()
    configured = Path(settings["paths"]["conversation_db"])
    database_path = (
        configured if configured.is_absolute() else root / configured
    ).resolve()
    if not database_path.is_relative_to(root):
        raise ValueError("Configured conversation database must remain inside V_HOME.")
    return ConversationStore(database_path)


def _memory_backfill_store() -> MemoryBackfillStore:
    return MemoryBackfillStore(_memory_store().database_path)


def _print_backfill_status() -> int:
    run = _memory_backfill_store().latest_run()
    if run is None:
        print("No historical memory backfill has been started.")
        return 0
    print(f"Run: {run['id']}")
    print(f"Status: {run['status']}")
    print(
        f"Messages: {run['processed_messages']} / {run['total_messages']} "
        f"({run['candidates_found']} proposals; "
        f"{run['candidates_skipped']} candidates skipped)"
    )
    print(f"Checkpoint message ID: {run['cursor_message_id']}")
    if run["last_error"]:
        print(f"Last error: {run['last_error']}")
    return 0


async def _run_memory_backfill(
    *,
    batch_size: int,
    new_run: bool,
) -> int:
    settings = load_settings()
    memory_settings = settings.get("memory", {})
    if not bool(memory_settings.get("enabled", True)):
        raise ValueError("Enable long-term memory before running historical backfill.")

    llm = settings["llm"]
    model = str(llm.get("model", "")).strip()
    if not model:
        raise ValueError("No chat model is configured.")

    memory_store = _memory_store()
    conversations = _conversation_store()
    queue = ExtractionQueue(memory_store.database_path)
    policy = NetworkPolicy.from_settings(settings)
    inference_url = policy.authorize_local_endpoint(llm.get("base_url", ""))
    provider = LMStudioProvider(
        base_url=inference_url,
        model=model,
        timeout_seconds=float(llm.get("request_timeout_seconds", 120)),
    )
    try:
        available = await provider.list_models()
        if model not in available:
            raise RuntimeError(
                f"Configured model '{model}' is not loaded in LM Studio."
            )
        extractor = MemoryExtractor(
            provider,
            conversations,
            memory_store,
            queue,
            min_confidence=float(memory_settings.get("minimum_confidence", 0.90)),
        )
        review_store = MemoryBackfillStore(memory_store.database_path)
        runner = MemoryBackfillRunner(
            conversations,
            extractor,
            memory_store,
            review_store,
            batch_size=batch_size,
        )

        print("Historical memory scan uses the configured local LM Studio model.")
        print("Existing saved memories will not be overwritten.")
        def report(progress: dict) -> None:
            print(
                f"Scanned {progress['processed_messages']}/"
                f"{progress['total_messages']} messages; "
                f"{progress['candidates_found']} proposals; "
                f"{progress['candidates_skipped']} skipped."
            )

        result = await runner.run(new_run=new_run, on_progress=report)
        print(
            f"Backfill {result['status']}: "
            f"{result['processed_messages']}/{result['total_messages']} messages, "
            f"{result['candidates_found']} proposals awaiting review, "
            f"{result['candidates_skipped']} skipped."
        )
        print("Review proposals with: python -m v memory review list")
        return 0
    finally:
        await provider.aclose()


def _run_memory_review_list(*, status: str, limit: int) -> int:
    review_store = _memory_backfill_store()
    candidates = review_store.list_candidates(status=status, limit=limit)
    if not candidates:
        print(f"No {status} memory proposals.")
        return 0
    for item in candidates:
        proposal = item["payload"]
        print(f"\nID: {item['id']}  Status: {item['status']}")
        print(
            f"Type: {proposal['memory_type']}  "
            f"Importance: {proposal['importance']}/5  "
            f"Confidence: {proposal['confidence']:.2f}"
        )
        print(f"Subject: {proposal['subject']}")
        print(f"Suggested summary: {proposal['model_content']}")
        print(f"Evidence: {proposal['evidence']}")
        print(f"Memory key: {proposal['memory_key']}")
        conflict = proposal.get("conflict", {})
        existing = conflict.get("existing_memory", {}) if isinstance(conflict, dict) else {}
        if existing:
            print("Existing saved memory (unchanged):")
            print(f"  ID: {existing.get('id')}")
            print(f"  Type: {existing.get('memory_type')}")
            print(f"  Content: {existing.get('content')}")
            print(f"  Key: {existing.get('memory_key')}")
            print(
                "  To approve both statements, pass --memory-key with a new unique key."
            )
        print(
            f"Source message: {proposal['source_message_id']} "
            f"({proposal.get('source_created_at', 'timestamp unavailable')})"
        )
        if item["review_note"]:
            print(f"Review note: {item['review_note']}")
    print()
    return 0


def _run_memory_review_approve(candidate_id: str, changes: dict) -> int:
    memory_store = _memory_store()
    review_store = MemoryBackfillStore(memory_store.database_path)
    memory = MemoryReviewService(memory_store, review_store).approve_candidate(
        candidate_id,
        changes=changes,
    )
    print(f"Approved proposal and created memory {memory.id}.")
    print(f"Stored content: {memory.content}")
    print(f"Evidence: {memory.evidence}")
    return 0


def _run_memory_review_reject(candidate_id: str, reason: str) -> int:
    memory_store = _memory_store()
    review_store = MemoryBackfillStore(memory_store.database_path)
    MemoryReviewService(memory_store, review_store).reject_candidate(
        candidate_id,
        reason=reason,
    )
    print("Proposal rejected. Its review record was retained.")
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

    confirm_parser = memory_actions.add_parser(
        "confirm",
        help="Record that a saved memory is still true, preserving its source.",
    )
    confirm_parser.add_argument("memory_id", help="Full memory ID.")

    backfill_parser = memory_actions.add_parser(
        "backfill",
        help="Reprocess historical conversations into a review queue.",
    )
    backfill_parser.add_argument(
        "--batch-size",
        type=int,
        choices=range(1, 21),
        default=5,
        help="User messages per local extraction request (default: 5).",
    )
    backfill_parser.add_argument(
        "--new-run",
        action="store_true",
        help="Start a new full-history scan instead of resuming the latest one.",
    )
    backfill_parser.add_argument(
        "--status",
        action="store_true",
        help="Show the latest scan status without contacting the model.",
    )

    review_parser = memory_actions.add_parser(
        "review",
        help="Inspect, approve, or reject historical memory proposals.",
    )
    review_actions = review_parser.add_subparsers(dest="review_action")
    review_list = review_actions.add_parser("list", help="List review proposals.")
    review_list.add_argument(
        "--status",
        choices=("pending", "approved", "rejected", "duplicate", "all"),
        default="pending",
    )
    review_list.add_argument("--limit", type=int, default=100)

    review_approve = review_actions.add_parser(
        "approve",
        help="Approve one proposal; optional fields let you edit it first.",
    )
    review_approve.add_argument("candidate_id")
    review_approve.add_argument("--content")
    review_approve.add_argument("--subject")
    review_approve.add_argument(
        "--memory-type",
        choices=("profile", "preference", "episodic", "relationship", "project", "fact"),
    )
    review_approve.add_argument("--memory-key")
    review_approve.add_argument("--confidence", type=float)
    review_approve.add_argument("--importance", type=int, choices=range(1, 6))

    review_reject = review_actions.add_parser(
        "reject",
        help="Reject a proposal while retaining its review record.",
    )
    review_reject.add_argument("candidate_id")
    review_reject.add_argument("--reason", default="")

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
            if args.memory_action == "backfill":
                if args.status:
                    if args.new_run:
                        raise ValueError("--status and --new-run cannot be combined.")
                    return _print_backfill_status()
                return asyncio.run(
                    _run_memory_backfill(
                        batch_size=args.batch_size,
                        new_run=args.new_run,
                    )
                )

            if args.memory_action == "review":
                if args.review_action == "list":
                    if args.limit < 1:
                        raise ValueError("--limit must be positive.")
                    return _run_memory_review_list(
                        status=args.status,
                        limit=args.limit,
                    )
                if args.review_action == "approve":
                    changes = {
                        key: value
                        for key, value in {
                            "content": args.content,
                            "subject": args.subject,
                            "memory_type": args.memory_type,
                            "memory_key": args.memory_key,
                            "confidence": args.confidence,
                            "importance": args.importance,
                        }.items()
                        if value is not None
                    }
                    return _run_memory_review_approve(
                        args.candidate_id,
                        changes,
                    )
                if args.review_action == "reject":
                    return _run_memory_review_reject(
                        args.candidate_id,
                        args.reason,
                    )
                review_parser.print_help()
                return 0

            if args.memory_action == "confirm":
                return _run_memory_confirm(args.memory_id)

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
