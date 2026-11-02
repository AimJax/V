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
from v.memory.embedding_provider import LMStudioEmbeddingProvider
from v.memory.evaluation import (
    DEFAULT_THRESHOLDS,
    create_personal_cases_template,
    evaluate_memory_retrieval,
    evaluate_personal_memory_retrieval,
    generate_personal_evaluation_cases,
    load_personal_cases,
    resolve_personal_cases_path,
)
from v.memory.backfill import (
    MemoryBackfillRunner,
    MemoryBackfillStore,
    MemoryReviewService,
)
from v.memory.extractor import MemoryExtractor
from v.memory.queue import ExtractionQueue
from v.memory.store import MemoryStore
from v.providers.errors import ProviderError
from v.providers.lm_studio import LMStudioProvider


def _memory_store(*, read_only: bool = False) -> MemoryStore:
    settings = load_settings()
    root = project_root().resolve()
    configured = Path(settings["paths"]["memory_db"])
    database_path = (
        configured if configured.is_absolute() else root / configured
    ).resolve()

    if not database_path.is_relative_to(root):
        raise ValueError("Configured memory database must remain inside V_HOME.")

    return MemoryStore(database_path, read_only=read_only)


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



async def _run_memory_evaluation(
    *,
    personal: bool = False,
    cases_path: str | None = None,
    limit: int = 5,
) -> int:
    """Run a synthetic or personalized local-only memory retrieval evaluation."""
    settings = load_settings()
    memory_settings = settings.get("memory", {})
    llm_settings = settings.get("llm", {})
    model = str(
        memory_settings.get(
            "embedding_model",
            "text-embedding-nomic-embed-text-v1.5",
        )
    ).strip()
    if not model:
        raise ValueError("No memory embedding model is configured.")

    configured_threshold = float(
        memory_settings.get("semantic_threshold", 0.60)
    )
    thresholds = tuple(sorted(set(DEFAULT_THRESHOLDS) | {configured_threshold}))

    memory_store = None
    personal_cases = None
    selected_cases_path = None
    case_generation = None
    if personal:
        memory_store = _memory_store(read_only=True)
        if cases_path is not None:
            selected_cases_path = resolve_personal_cases_path(cases_path)
            personal_cases = load_personal_cases(
                selected_cases_path,
                {memory.id for memory in memory_store.list_memories(limit=10000)},
            )

    policy = NetworkPolicy.from_settings(settings)
    endpoint = policy.authorize_local_endpoint(
        str(llm_settings.get("base_url", ""))
    )
    timeout = float(llm_settings.get("request_timeout_seconds", 120))
    provider = None
    chat_provider = None
    try:
        if personal and cases_path is None:
            chat_model = str(llm_settings.get("model", "")).strip()
            if not chat_model:
                raise ValueError(
                    "Configure llm.model before running automatic personal evaluation."
                )
            chat_provider = LMStudioProvider(
                base_url=endpoint,
                model=chat_model,
                timeout_seconds=timeout,
            )
            memories = memory_store.list_memories(limit=10000)
            personal_cases, case_generation = await generate_personal_evaluation_cases(
                memories,
                chat_provider,
                model=chat_model,
            )

        provider = LMStudioEmbeddingProvider(
            base_url=endpoint,
            model=model,
            timeout_seconds=timeout,
        )
        if personal:
            report = await evaluate_personal_memory_retrieval(
                memory_store,
                provider,
                personal_cases,
                model=model,
                thresholds=thresholds,
                limit=limit,
            )
            if case_generation is not None:
                report["case_generation"] = case_generation
        else:
            report = await evaluate_memory_retrieval(
                provider,
                model=model,
                thresholds=thresholds,
                limit=limit,
            )
    except ProviderError as error:
        print(f"Memory evaluation failed: {error}", file=sys.stderr)
        return 1
    finally:
        if provider is not None:
            await provider.aclose()
        if chat_provider is not None:
            await chat_provider.aclose()

    fts = report["fts_baseline"]
    mode = "personal memory" if personal else "synthetic"
    print(f"\nV memory retrieval benchmark ({mode})")
    print("=" * (34 + len(mode)))
    print(f"Embedding model: {report['model']}")
    print(f"Current configured threshold: {configured_threshold:.2f}")
    if personal:
        if selected_cases_path is None:
            print("Evaluation cases: generated locally (no file)")
        else:
            print(f"Evaluation cases: {selected_cases_path}")
        print(
            f"Saved memories: {report['memory_count']}  "
            f"Queries: {report['query_count']} "
            f"({report['positive_queries']} answerable, "
            f"{report['negative_queries']} no-answer)"
        )
        if "case_generation" in report:
            generated = report["case_generation"]
            print(
                f"Questions generated locally: {generated['generated_queries']} "
                f"from {generated['sampled_memories']} sampled memories "
                f"(chat model: {generated['model']})"
            )
            print(
                f"Plain-text retries: {generated['plain_text_retries']}; "
                f"deterministic fallbacks: {generated['deterministic_fallbacks']}"
            )
            print("Generated test cases kept in RAM; no label file was created.")
            print("Question generation methods:")
            print(
                f"  JSON: {sum(item['generation_method'] == 'json' for item in generated['question_previews'])}; "
                f"plain text: {sum(item['generation_method'] == 'plain_text' for item in generated['question_previews'])}; "
                f"deterministic: {sum(item['generation_method'] == 'deterministic' for item in generated['question_previews'])}"
            )
        print(
            f"Embedding cache reused: {report['cached_embeddings_reused']}  "
            f"New vectors generated in RAM: "
            f"{report['embeddings_generated_in_memory']}"
        )
    else:
        print(
            f"Isolated corpus: {report['corpus_size']} synthetic memories; "
            f"{report['query_count']} queries "
            f"({report['positive_queries']} answerable, "
            f"{report['negative_queries']} no-answer)"
        )
    fts_false_positive = (
        "n/a"
        if fts["false_positive_rate"] is None
        else f"{fts['false_positive_rate']:.3f}"
    )
    print(
        "FTS5-only baseline: "
        f"P={fts['precision']:.3f}  R={fts['recall']:.3f}  "
        f"MRR={fts['mrr']:.3f}  "
        f"no-answer FP={fts_false_positive}"
    )
    print()
    print("Threshold  Precision  Recall  MRR     No-answer FP  Score")
    for item in report["thresholds"]:
        print(
            f"{item['threshold']:>9.2f}  "
            f"{item['precision']:>9.3f}  "
            f"{item['recall']:>6.3f}  "
            f"{item['mrr']:>5.3f}  "
            f"{('n/a' if item['false_positive_rate'] is None else format(item['false_positive_rate'], '.3f')):>13}  "
            f"{item['selection_score']:>5.3f}"
        )
    if personal:
        print()
        print("Per-question results at the top-scoring threshold:")
        details = report["query_details"][report["best_scoring_threshold"]]
        for item in details:
            if item["relevant_memory_ids"]:
                status = (
                    "MISS"
                    if item["missing_relevant_memory_ids"]
                    else "HIT"
                )
                coverage = (
                    f"{len(item['relevant_memory_ids']) - len(item['missing_relevant_memory_ids'])}"
                    f"/{len(item['relevant_memory_ids'])} relevant"
                )
            else:
                status = "FALSE POSITIVE" if item["false_positive"] else "REJECTED"
                coverage = "no-answer"
            print(
                f"  Q{item['case']:02d} [{status}] {coverage}; "
                f"returned={item['returned_count']}; "
                f"context={item['context_characters']} chars"
            )
            generated_questions = report.get("case_generation", {}).get("question_previews", [])
            if item["case"] <= len(generated_questions):
                preview = generated_questions[item["case"] - 1]
                print(
                    f"      source={preview['subject']} "
                    f"({preview['generation_method']})"
                )
                print(f"      query={preview['query']}")
        best_result = next(
            item for item in report["thresholds"]
            if item["threshold"] == report["best_scoring_threshold"]
        )
        print(
            "Average context size at selected threshold: "
            f"{best_result['mean_context_characters']:.0f} characters"
        )
        print("Persistent database/cache writes: none.")
    print()
    print(
        "Top-scoring calibration candidate: "
        f"{report['best_scoring_threshold']:.2f}"
    )
    print(report["selection_note"])
    print("No threshold was applied to configuration.")
    return 0


def _run_memory_evaluation_init(destination: str | None = None) -> int:
    """Create a local-only JSON file for human-labeled retrieval cases."""
    path = create_personal_cases_template(destination)
    print(f"Created personal memory evaluation template: {path}")
    print("Optional advanced workflow: edit 'cases' and label memory IDs manually. The normal --personal command generates cases automatically.")
    print("Find IDs with /memory search in chat or in the Memory Manager.")
    print("The file is under V's ignored data directory and is not committed to Git.")
    return 0


def _run_memory_confirm(memory_id: str) -> int:
    try:
        memory = _memory_store().confirm_memory(memory_id)
    except KeyError:
        print(f"Memory ID not found: {memory_id}", file=sys.stderr)
        return 1
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
        help="Manage and evaluate local long-term memories.",
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

    evaluate_parser = memory_actions.add_parser(
        "evaluate",
        help="Benchmark local memory retrieval without touching saved memories.",
    )
    evaluate_parser.add_argument(
        "--personal",
        action="store_true",
        help="Generate local questions from saved memories and evaluate real retrieval.",
    )
    evaluate_parser.add_argument(
        "--cases",
        help=(
            "Optional manually labeled evaluation file (must be inside V_HOME). "
            "Omit this to let V generate questions locally."
        ),
    )
    evaluate_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum retrieved memories per question (default: 5).",
    )

    eval_init_parser = memory_actions.add_parser(
        "eval-init",
        help="Create an optional private template for manually labeled retrieval evaluation.",
    )
    eval_init_parser.add_argument(
        "--destination",
        help="Optional destination inside V_HOME.",
    )

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
            if args.memory_action == "evaluate":
                if args.cases and not args.personal:
                    raise ValueError("--cases requires --personal.")
                return asyncio.run(
                    _run_memory_evaluation(
                        personal=args.personal,
                        cases_path=args.cases,
                        limit=args.limit,
                    )
                )

            if args.memory_action == "eval-init":
                return _run_memory_evaluation_init(args.destination)

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
