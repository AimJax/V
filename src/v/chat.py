"""Interactive streaming conversation with V."""

from __future__ import annotations

import asyncio
import re
import shlex

from pathlib import Path

from v.core.config import load_settings, project_root
from v.core.network import NetworkPolicy
from v.conversations.store import Conversation, ConversationStore
from v.memory.embedding_provider import LMStudioEmbeddingProvider
from v.memory.backfill import MemoryBackfillStore
from v.memory.embedding_store import EmbeddingStore
from v.memory.extractor import MemoryExtractor
from v.memory.hybrid_retrieval import HybridMemoryRetriever
from v.memory.queue import ExtractionQueue
from v.memory.retrieval import (
    build_memory_context,
    meaningful_terms,
)
from v.memory.store import MemoryStore
from v.memory.worker import MemoryWorker
from v.providers.base import ChatMessage
from v.providers.errors import ProviderError
from v.providers.lm_studio import LMStudioProvider


def load_personality(settings: dict) -> str:
    relative_path = Path(settings["paths"]["personality"])

    if not relative_path.is_absolute():
        relative_path = project_root() / relative_path

    try:
        return relative_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(
            f"Could not read personality file: {relative_path}"
        ) from error


def _configured_data_path(settings: dict, key: str) -> Path:
    root = project_root().resolve()
    configured = Path(settings["paths"][key])

    path = configured if configured.is_absolute() else root / configured
    path = path.resolve()

    if not path.is_relative_to(root):
        raise ValueError(
            f"Configured path '{key}' must remain inside G:\\V."
        )

    return path


_MEMORY_FOLLOW_UP_PREFIXES = (
    "and ",
    "but ",
    "also ",
    "what about",
    "how about",
    "what if",
    "why is that",
    "why does it",
    "why do they",
    "how does it",
    "how do they",
    "does it",
    "did it",
    "is it",
    "is that",
    "was it",
    "are they",
    "do they",
    "can it",
    "could it",
    "would it",
    "will it",
    "which one",
    "what do you mean",
    "can you explain that",
    "could you explain that",
    "explain that",
    "tell me more",
    "more detail",
    "more details",
    "elaborate",
    "expand on",
    "what next",
    "what now",
    "what do we do next",
    "what should we do next",
    "next step",
)

_MEMORY_REFERENCE_WORDS = {
    "it", "its", "this", "that", "they", "them", "their",
    "these", "those", "one", "ones", "there",
}


def _is_contextual_follow_up(user_input: str) -> bool:
    """Identify turns whose meaning likely depends on recent dialogue."""
    normalized = " ".join(user_input.casefold().split())
    if not normalized:
        return False

    if any(normalized.startswith(prefix) for prefix in _MEMORY_FOLLOW_UP_PREFIXES):
        return True

    if normalized in {"why?", "why", "how?", "how"}:
        return True

    if not normalized.endswith("?"):
        return False

    words = set(re.findall(r"[\w]+", normalized, flags=re.UNICODE))
    return (
        len(meaningful_terms(normalized)) <= 3
        and bool(words & _MEMORY_REFERENCE_WORDS)
    )


def build_memory_retrieval_query(
    user_input: str,
    recent_messages: list[ChatMessage],
    *,
    max_messages: int = 4,
    max_context_characters: int = 1600,
) -> str:
    """Resolve follow-up references using recent dialogue without another LLM call.

    Standalone user turns remain unchanged so unrelated older topics do not
    contaminate memory retrieval. Only likely follow-ups receive bounded context.
    """
    if max_messages < 1 or max_context_characters < 1:
        raise ValueError("Memory retrieval context limits must be positive.")

    if not _is_contextual_follow_up(user_input):
        return user_input

    context_lines: list[str] = []
    for message in recent_messages[-max_messages:]:
        content = " ".join(message.content.split())
        if not content:
            continue
        if len(content) > 600:
            content = content[-600:]
        context_lines.append(f"{message.role}: {content}")

    if not context_lines:
        return user_input

    context = "\n".join(context_lines)[-max_context_characters:]
    return (
        "Recent conversation context (use only to resolve the current reference):\n"
        f"{context}\n"
        "Current user message:\n"
        f"{user_input}"
    )


def _build_messages(
    personality: str,
    store: ConversationStore,
    conversation: Conversation,
    history_limit: int,
    *,
    memory_context: str | None = None,
) -> list[ChatMessage]:
    """Build one system message plus the selected conversation history."""
    system_content = personality

    if memory_context:
        system_content += "\n\n" + memory_context

    return [
        ChatMessage(role="system", content=system_content),
        *store.get_recent_messages(conversation.id, history_limit),
    ]


def trim_history(
    messages: list[ChatMessage],
    history_limit: int,
) -> None:
    """Keep system instructions and the latest conversation messages."""
    if history_limit < 2:
        raise ValueError("history_messages must be at least 2.")

    system_messages = [
        message for message in messages
        if message.role == "system"
    ]

    conversation = [
        message for message in messages
        if message.role != "system"
    ]

    messages[:] = [
        *system_messages,
        *conversation[-history_limit:],
    ]


def _print_sessions(store: ConversationStore) -> None:
    sessions = store.list_conversations(limit=20)

    if not sessions:
        print("\nNo saved conversations.\n")
        return

    print("\nRecent conversations:")

    for index, session in enumerate(sessions, start=1):
        updated = session.updated_at.replace("T", " ")[:19]
        print(f"  {index:>2}. {session.title} [{updated}]")

    print("\nUse /resume N to open a conversation.\n")


def _correct_memory(memory_store: MemoryStore, user_input: str) -> None:
    """Apply one explicit, user-requested correction to a saved memory."""
    try:
        parts = shlex.split(user_input)
    except ValueError as error:
        print(f"Invalid correction syntax: {error}\n")
        return

    if len(parts) < 5:
        print(
            "Usage: /memory correct ID FIELD VALUE\n"
            "Fields: content, subject, type, key, confidence, importance, evidence\n"
            "Use --clear to clear an optional key or evidence field.\n"
        )
        return

    memory_id, field = parts[2], parts[3].casefold()
    value = " ".join(parts[4:])
    field_map = {
        "content": "content",
        "subject": "subject",
        "type": "memory_type",
        "key": "memory_key",
        "confidence": "confidence",
        "importance": "importance",
        "evidence": "evidence",
    }

    if field not in field_map:
        print("Unsupported field. Use /memory correct to see supported fields.\n")
        return

    target_field = field_map[field]

    try:
        if value == "--clear":
            if target_field not in {"memory_key", "evidence"}:
                raise ValueError("--clear is only valid for key and evidence.")

            parsed_value = None
        elif target_field == "confidence":
            parsed_value = float(value)
        elif target_field == "importance":
            parsed_value = int(value)
        elif target_field == "memory_type":
            parsed_value = value.casefold()
        else:
            parsed_value = value

        memory = memory_store.update_memory(
            memory_id,
            **{target_field: parsed_value},
        )
    except (KeyError, TypeError, ValueError) as error:
        print(f"Memory correction failed: {error}\n")
        return

    print("\nMemory corrected:")
    print(f"  ID: {memory.id}")
    print(f"  Type: {memory.memory_type}")
    print(f"  Subject: {memory.subject}")
    print(f"  Content: {memory.content}")
    print(f"  Importance: {memory.importance}/5")
    print(f"  Confidence: {memory.confidence:.2f}\n")


def _print_memories(
    memory_store: MemoryStore,
    *,
    query: str | None = None,
) -> None:
    memories = (
        memory_store.search_memories(query, limit=20)
        if query
        else memory_store.list_memories(limit=20)
    )

    if not memories:
        print("\nNo matching memories.\n")
        return

    print("\nV's saved memories:")

    for memory in memories:
        print(f"\nID: {memory.id}")
        print(f"Type: {memory.memory_type}")
        print(f"Subject: {memory.subject}")
        print(f"Content: {memory.content}")
        print(f"Source: {memory.provenance}")
        print(f"Confidence: {memory.confidence:.2f}")
        print(f"Importance: {memory.importance}/5")

    print()


async def run_chat() -> int:
    settings = load_settings()
    llm = settings["llm"]
    memory_settings = settings.get("memory", {})

    model = str(llm.get("model", "")).strip()

    if not model:
        print("No model configured. Set llm.model in config/default.toml.")
        return 1

    provider = None
    embedding_provider = None
    memory_worker = None

    try:
        personality = load_personality(settings)

        conversation_store = ConversationStore(
            _configured_data_path(settings, "conversation_db")
        )

        memory_enabled = bool(memory_settings.get("enabled", True))
        automatic_memory = (
            memory_enabled
            and bool(memory_settings.get("automatic_extraction", True))
        )
        memory_retrieval = (
            memory_enabled
            and bool(memory_settings.get("retrieval_enabled", True))
        )

        memory_store = None
        extraction_queue = None
        memory_review_store = None
        retriever = None

        if memory_enabled:
            memory_database = _configured_data_path(
                settings,
                "memory_db",
            )

            memory_store = MemoryStore(memory_database)
            extraction_queue = ExtractionQueue(memory_database)
            memory_review_store = MemoryBackfillStore(memory_database)

        network_policy = NetworkPolicy.from_settings(settings)
        inference_base_url = network_policy.authorize_local_endpoint(
            llm["base_url"]
        )

        provider = LMStudioProvider(
            base_url=inference_base_url,
            model=model,
            timeout_seconds=float(
                llm.get("request_timeout_seconds", 120)
            ),
        )

        history_limit = int(llm.get("history_messages", 24))
        temperature = float(llm.get("temperature", 0.7))
        max_tokens = int(llm.get("max_tokens", 512))

        retrieval_limit = int(
            memory_settings.get("retrieval_limit", 5)
        )
        retrieval_max_characters = int(
            memory_settings.get("retrieval_max_characters", 2400)
        )

        if automatic_memory:
            extractor = MemoryExtractor(
                provider,
                conversation_store,
                memory_store,
                extraction_queue,
                min_confidence=float(
                    memory_settings.get("minimum_confidence", 0.90)
                ),
                conflict_store=memory_review_store,
            )

            memory_worker = MemoryWorker(
                extractor,
                idle_delay_seconds=float(
                    memory_settings.get("idle_delay_seconds", 20)
                ),
                max_jobs_per_cycle=int(
                    memory_settings.get("max_jobs_per_idle_cycle", 3)
                ),
            )

        print("\nV — Local AI Companion")
        print("======================")
        print("Connecting to LM Studio...")

        available_models = await provider.list_models()

        if model not in available_models:
            print(f"\nConfigured model is unavailable: {model}")
            print("Models exposed by LM Studio:")

            for available_model in available_models:
                print(f"  - {available_model}")

            print("\nLoad the configured model in LM Studio.")
            return 1

        # Verify the selected local embedding model.
        embedding_model = str(
            memory_settings.get(
                "embedding_model",
                "text-embedding-nomic-embed-text-v1.5",
            )
        )

        if (
            memory_retrieval
            and memory_store is not None
            and embedding_model in available_models
        ):
            embedding_provider = LMStudioEmbeddingProvider(
                base_url=inference_base_url,
                model=embedding_model,
                timeout_seconds=float(
                    llm.get("request_timeout_seconds", 120)
                ),
            )

            embedding_store = EmbeddingStore(
                _configured_data_path(settings, "memory_db")
            )

            retriever = HybridMemoryRetriever(
                memory_store,
                embedding_store,
                embedding_provider,
                model=embedding_model,
                semantic_threshold=float(
                    memory_settings.get("semantic_threshold", 0.60)
                ),
                limit=retrieval_limit,
            )

            print(f"Semantic memory retrieval: ENABLED ({embedding_model})")

        elif memory_retrieval:
            print(
                "Warning: embedding model is not loaded. "
                "Using local keyword retrieval."
            )

        conversation = conversation_store.get_latest_conversation()

        if conversation is None:
            conversation = conversation_store.create_conversation()

        restored = conversation_store.get_recent_messages(
            conversation.id,
            history_limit,
        )

        print(f"Connected: {model}")
        print(f"Network policy: {network_policy.mode_label}")
        print(f"Conversation database: {conversation_store.database_path}")

        if memory_store is not None:
            print(f"Memory database: {memory_store.database_path}")

        print(f"Conversation: {conversation.title}")
        print(f"Restored messages: {len(restored)}")
        print("\nCommands: /help, /new, /sessions, /resume N,")
        print("          /memory, /memory search TEXT, /memory status,")
        print("          /memory correct ID FIELD VALUE, /memory delete ID,")
        print("          /memory retry, /exit")
        print("\nV is ready.\n")

        # Resume pending extraction jobs after application restart.
        if memory_worker is not None and extraction_queue.count("pending"):
            await memory_worker.schedule()

        while True:
            try:
                user_input = await asyncio.to_thread(input, "You: ")
            except EOFError:
                print("\nConversation ended.")
                break

            user_input = user_input.strip()

            if not user_input:
                continue

            command = user_input.lower()

            if command in {"/exit", "/quit"}:
                print("V: Goodbye.")
                break

            if command == "/help":
                print("\nCommands:")
                print("  /help                 - Show commands")
                print("  /new                  - Start a new conversation")
                print("  /sessions             - List saved conversations")
                print("  /resume N             - Resume a listed conversation")
                print("  /memory               - List saved memories")
                print("  /memory search TEXT   - Search saved memories")
                print("  /memory status        - Show memory counts")
                print("  /memory correct ID FIELD VALUE - Correct a saved memory")
                print("  /memory confirm ID    - Confirm a saved memory is still true")
                print("  /memory delete ID     - Permanently delete a memory")
                print("  /memory retry         - Retry failed extraction jobs")
                print("  /exit                 - Exit V\n")
                continue

            if command == "/new":
                conversation = conversation_store.create_conversation()
                print("\nStarted a new conversation.\n")
                continue

            if command == "/sessions":
                _print_sessions(conversation_store)
                continue

            if command == "/memory" or command == "/memory list":
                if memory_store is None:
                    print("\nMemory is disabled in configuration.\n")
                else:
                    _print_memories(memory_store)
                continue

            if command.startswith("/memory "):
                parts = user_input.split(maxsplit=2)
                subcommand = parts[1].lower() if len(parts) > 1 else ""

                if memory_store is None or extraction_queue is None:
                    print("\nMemory is disabled in configuration.\n")
                    continue

                if subcommand == "search":
                    if len(parts) < 3 or not parts[2].strip():
                        print("Usage: /memory search TEXT\n")
                    else:
                        _print_memories(memory_store, query=parts[2])
                    continue

                if subcommand == "status":
                    print("\nMemory status:")
                    print(f"  Saved memories: {memory_store.count_memories()}")
                    print(f"  Pending jobs: {extraction_queue.count('pending')}")
                    print(f"  Completed jobs: {extraction_queue.count('completed')}")
                    print(f"  Failed jobs: {extraction_queue.count('failed')}")

                    if memory_worker is None:
                        print("  Background worker: disabled")
                    else:
                        state = "active" if memory_worker.running else "idle"
                        print(f"  Background worker: {state}")

                        if memory_worker.last_error:
                            print(
                                "  Last worker error: "
                                f"{memory_worker.last_error[:300]}"
                            )

                        report = memory_worker.last_report
                        if report is not None:
                            print(
                                "  Last extraction cycle: "
                                f"{report.jobs_completed} completed, "
                                f"{report.jobs_failed} failed, "
                                f"{report.memories_created} memories saved, "
                                f"{report.conflicts_queued} conflicts queued for review, "
                                f"{report.candidates_skipped} candidates skipped"
                            )

                    failed_jobs = extraction_queue.list_failed(limit=3)
                    if failed_jobs:
                        print("  Recent failed extraction jobs:")
                        for job in failed_jobs:
                            detail = (
                                job["last_error"] or "No error detail recorded."
                            )[:240]
                            print(
                                f"    Message {job['source_message_id']} "
                                f"(attempts: {job['attempts']}): {detail}"
                            )

                    if retriever is not None and retriever.last_fallback_reason:
                        print("  Semantic retrieval: fallback mode")
                    elif retriever is not None:
                        print("  Semantic retrieval: enabled")
                    else:
                        print("  Semantic retrieval: unavailable")

                    print()
                    continue

                if subcommand == "confirm":
                    if len(parts) != 3:
                        print("Usage: /memory confirm FULL_MEMORY_ID\n")
                    else:
                        try:
                            memory = memory_store.confirm_memory(parts[2].strip())
                        except KeyError:
                            print("Memory ID not found.\n")
                        else:
                            print(
                                "Memory confirmed at "
                                f"{memory.last_confirmed_at}. Original source date "
                                f"remains {memory.source_created_at or 'unknown'}.\n"
                            )
                    continue

                if subcommand == "delete":
                    if len(parts) != 3:
                        print("Usage: /memory delete FULL_MEMORY_ID\n")
                    elif memory_store.delete_memory(parts[2].strip()):
                        print("Memory permanently deleted.\n")
                    else:
                        print("Memory ID not found.\n")
                    continue

                if subcommand == "correct":
                    _correct_memory(memory_store, user_input)
                    continue

                if subcommand == "retry":
                    retried = extraction_queue.retry_failed()
                    print(f"Reset {retried} failed extraction job(s).\n")

                    if retried and memory_worker:
                        await memory_worker.schedule()
                    continue

                print("Unknown memory command. Use /help.\n")
                continue

            if command.startswith("/resume"):
                parts = user_input.split(maxsplit=1)

                if len(parts) != 2 or not parts[1].isdigit():
                    print("Usage: /resume N (use /sessions to see numbers)\n")
                    continue

                sessions = conversation_store.list_conversations(limit=20)
                index = int(parts[1])

                if index < 1 or index > len(sessions):
                    print("Invalid session number. Use /sessions.\n")
                    continue

                conversation = sessions[index - 1]
                print(f"\nResumed: {conversation.title}")
                print(
                    "Restored messages: "
                    f"{len(conversation_store.get_recent_messages(conversation.id, history_limit))}\n"
                )
                continue

            # A new user turn always takes priority over background extraction.
            if memory_worker is not None:
                await memory_worker.cancel()

            memory_context = None

            if memory_store is not None and memory_retrieval:
                try:
                    recent_dialogue = conversation_store.get_recent_messages(
                        conversation.id,
                        min(history_limit, 4),
                    )
                    memory_query = build_memory_retrieval_query(
                        user_input,
                        recent_dialogue,
                    )

                    if retriever is not None:
                        relevant_memories = await retriever.retrieve(
                            memory_query,
                            limit=retrieval_limit,
                        )
                    else:
                        terms = meaningful_terms(memory_query)

                        relevant_memories = (
                            memory_store.search_memories_any(
                                " ".join(terms),
                                limit=retrieval_limit,
                            )
                            if terms
                            else []
                        )

                    memory_context = build_memory_context(
                        relevant_memories,
                        max_characters=retrieval_max_characters,
                    )

                except Exception as error:
                    # Memory retrieval must never prevent a conversation.
                    print(
                        f"\n[Memory retrieval unavailable: {error}]"
                    )

            messages = _build_messages(
                personality,
                conversation_store,
                conversation,
                history_limit,
                memory_context=memory_context,
            )

            messages.append(
                ChatMessage(role="user", content=user_input)
            )

            print("\nV: ", end="", flush=True)
            response_parts: list[str] = []

            try:
                async for chunk in provider.stream_chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    response_parts.append(chunk)
                    print(chunk, end="", flush=True)

            except ProviderError as error:
                print(f"\n\n[Provider error: {error}]")
                print()
                continue

            except KeyboardInterrupt:
                print("\n\n[Generation interrupted]")
                print()
                continue

            response = "".join(response_parts)

            if response:
                source_message_id = conversation_store.add_message(
                    conversation.id,
                    "user",
                    user_input,
                )

                conversation_store.add_message(
                    conversation.id,
                    "assistant",
                    response,
                )

                if extraction_queue is not None:
                    extraction_queue.enqueue(
                        conversation.id,
                        source_message_id,
                    )

                if memory_worker is not None:
                    await memory_worker.schedule()

            else:
                print("[No response received]")

            print("\n")

    except ProviderError as error:
        print(f"\nLM Studio connection failed: {error}")
        print("Check the LM Studio local server.")
        return 1

    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
        print(f"\nV configuration or storage error: {error}")
        return 1

    finally:
        if memory_worker is not None:
            await memory_worker.close()

        if embedding_provider is not None:
            await embedding_provider.aclose()

        if provider is not None:
            await provider.aclose()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_chat()))