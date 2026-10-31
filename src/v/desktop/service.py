"""Application services shared by V's desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from v.chat import _configured_data_path, load_personality
from v.core.config import load_settings
from v.core.network import NetworkPolicy
from v.conversations.store import Conversation, ConversationStore
from v.memory.embedding_provider import LMStudioEmbeddingProvider
from v.memory.embedding_store import EmbeddingStore
from v.memory.extractor import MemoryExtractor
from v.memory.hybrid_retrieval import HybridMemoryRetriever
from v.memory.queue import ExtractionQueue
from v.memory.retrieval import build_memory_context, meaningful_terms
from v.memory.store import MemoryStore
from v.memory.worker import MemoryWorker
from v.providers.base import ChatMessage
from v.providers.errors import ProviderError, ProviderProtocolError
from v.providers.lm_studio import LMStudioProvider


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    """Data required to render a conversation and its application status."""

    conversation: Conversation
    conversations: list[Conversation]
    messages: list[ChatMessage]
    model: str
    network_mode: str
    semantic_memory_enabled: bool


@dataclass(frozen=True, slots=True)
class DesktopTurnResult:
    """Completed assistant response and refreshed session metadata."""

    response: str
    snapshot: DesktopSnapshot


class DesktopService:
    """Own local providers, persistence, memory, and conversation operations."""

    def __init__(self) -> None:
        self.settings: dict = {}
        self.provider: LMStudioProvider | None = None
        self.embedding_provider: LMStudioEmbeddingProvider | None = None
        self.conversation_store: ConversationStore | None = None
        self.memory_store: MemoryStore | None = None
        self.extraction_queue: ExtractionQueue | None = None
        self.memory_worker: MemoryWorker | None = None
        self.retriever: HybridMemoryRetriever | None = None
        self.conversation: Conversation | None = None
        self.model = ""
        self.network_mode = "UNKNOWN"
        self.history_limit = 24
        self.temperature = 0.7
        self.max_tokens = 512
        self.retrieval_limit = 5
        self.retrieval_max_characters = 2400
        self.personality = ""
        self.started = False

    async def start(self) -> DesktopSnapshot:
        """Connect only to the configured local model and load local state."""
        if self.started:
            raise RuntimeError("Desktop service is already running.")

        self.settings = load_settings()
        llm = self.settings["llm"]
        memory_settings = self.settings.get("memory", {})
        self.model = str(llm.get("model", "")).strip()

        if not self.model:
            raise ValueError("No chat model is configured in config/default.toml.")

        self.personality = load_personality(self.settings)
        self.conversation_store = ConversationStore(
            _configured_data_path(self.settings, "conversation_db")
        )

        network_policy = NetworkPolicy.from_settings(self.settings)
        inference_url = network_policy.authorize_local_endpoint(
            llm.get("base_url", "")
        )
        self.network_mode = network_policy.mode_label

        self.provider = LMStudioProvider(
            base_url=inference_url,
            model=self.model,
            timeout_seconds=float(llm.get("request_timeout_seconds", 120)),
        )

        available_models = await self.provider.list_models()
        if self.model not in available_models:
            raise ProviderProtocolError(
                f"Configured model '{self.model}' is not loaded in LM Studio."
            )

        self.history_limit = int(llm.get("history_messages", 24))
        self.temperature = float(llm.get("temperature", 0.7))
        self.max_tokens = int(llm.get("max_tokens", 512))
        self.retrieval_limit = int(memory_settings.get("retrieval_limit", 5))
        self.retrieval_max_characters = int(
            memory_settings.get("retrieval_max_characters", 2400)
        )

        memory_enabled = bool(memory_settings.get("enabled", True))
        memory_retrieval = (
            memory_enabled
            and bool(memory_settings.get("retrieval_enabled", True))
        )
        automatic_memory = (
            memory_enabled
            and bool(memory_settings.get("automatic_extraction", True))
        )

        if memory_enabled:
            memory_path = _configured_data_path(self.settings, "memory_db")
            self.memory_store = MemoryStore(memory_path)
            self.extraction_queue = ExtractionQueue(memory_path)

        if automatic_memory and self.memory_store and self.extraction_queue:
            extractor = MemoryExtractor(
                self.provider,
                self.conversation_store,
                self.memory_store,
                self.extraction_queue,
                min_confidence=float(
                    memory_settings.get("minimum_confidence", 0.90)
                ),
            )
            self.memory_worker = MemoryWorker(
                extractor,
                idle_delay_seconds=float(
                    memory_settings.get("idle_delay_seconds", 20)
                ),
                max_jobs_per_cycle=int(
                    memory_settings.get("max_jobs_per_idle_cycle", 3)
                ),
            )

        if memory_retrieval and self.memory_store is not None:
            embedding_model = str(
                memory_settings.get(
                    "embedding_model",
                    "text-embedding-nomic-embed-text-v1.5",
                )
            )
            if embedding_model in available_models:
                self.embedding_provider = LMStudioEmbeddingProvider(
                    base_url=inference_url,
                    model=embedding_model,
                    timeout_seconds=float(
                        llm.get("request_timeout_seconds", 120)
                    ),
                )
                embedding_store = EmbeddingStore(
                    _configured_data_path(self.settings, "memory_db")
                )
                self.retriever = HybridMemoryRetriever(
                    self.memory_store,
                    embedding_store,
                    self.embedding_provider,
                    model=embedding_model,
                    semantic_threshold=float(
                        memory_settings.get("semantic_threshold", 0.60)
                    ),
                    limit=self.retrieval_limit,
                )

        self.conversation = self.conversation_store.get_latest_conversation()
        if self.conversation is None:
            self.conversation = self.conversation_store.create_conversation()

        if (
            self.memory_worker is not None
            and self.extraction_queue is not None
            and self.extraction_queue.count("pending")
        ):
            await self.memory_worker.schedule()

        self.started = True
        return self.snapshot()

    def snapshot(self) -> DesktopSnapshot:
        if self.conversation_store is None or self.conversation is None:
            raise RuntimeError("Desktop service has not started.")

        return DesktopSnapshot(
            conversation=self.conversation,
            conversations=self.conversation_store.list_conversations(limit=50),
            messages=self.conversation_store.get_recent_messages(
                self.conversation.id,
                self.history_limit,
            ),
            model=self.model,
            network_mode=self.network_mode,
            semantic_memory_enabled=self.retriever is not None,
        )

    def new_conversation(self) -> DesktopSnapshot:
        if self.conversation_store is None:
            raise RuntimeError("Desktop service has not started.")

        self.conversation = self.conversation_store.create_conversation()
        return self.snapshot()

    def select_conversation(self, conversation_id: str) -> DesktopSnapshot:
        if self.conversation_store is None:
            raise RuntimeError("Desktop service has not started.")

        conversation = self.conversation_store.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"Conversation not found: {conversation_id}")

        self.conversation = conversation
        return self.snapshot()

    async def send_message(
        self,
        user_text: str,
        on_token: Callable[[str], None],
    ) -> DesktopTurnResult:
        """Stream one turn and persist it only after a complete response."""
        if (
            not self.started
            or self.provider is None
            or self.conversation_store is None
            or self.conversation is None
        ):
            raise RuntimeError("Desktop service is not ready.")

        user_text = user_text.strip()
        if not user_text:
            raise ValueError("Message cannot be empty.")

        if self.memory_worker is not None:
            await self.memory_worker.cancel()

        memory_context = None
        if self.memory_store is not None and self.settings.get(
            "memory", {}
        ).get("retrieval_enabled", True):
            try:
                if self.retriever is not None:
                    memories = await self.retriever.retrieve(
                        user_text,
                        limit=self.retrieval_limit,
                    )
                else:
                    terms = meaningful_terms(user_text)
                    memories = (
                        self.memory_store.search_memories_any(
                            " ".join(terms),
                            limit=self.retrieval_limit,
                        )
                        if terms
                        else []
                    )
                memory_context = build_memory_context(
                    memories,
                    max_characters=self.retrieval_max_characters,
                )
            except Exception:
                # Memory failures must never prevent the user from chatting.
                memory_context = None

        system_content = self.personality
        if memory_context:
            system_content += "\n\n" + memory_context

        messages = [
            ChatMessage(role="system", content=system_content),
            *self.conversation_store.get_recent_messages(
                self.conversation.id,
                self.history_limit,
            ),
            ChatMessage(role="user", content=user_text),
        ]

        response_parts: list[str] = []
        async for chunk in self.provider.stream_chat(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        ):
            response_parts.append(chunk)
            on_token(chunk)

        response = "".join(response_parts)
        if not response:
            raise ProviderProtocolError("LM Studio returned an empty response.")

        source_message_id = self.conversation_store.add_message(
            self.conversation.id,
            "user",
            user_text,
        )
        self.conversation_store.add_message(
            self.conversation.id,
            "assistant",
            response,
        )

        if self.extraction_queue is not None:
            self.extraction_queue.enqueue(
                self.conversation.id,
                source_message_id,
            )

        if self.memory_worker is not None:
            await self.memory_worker.schedule()

        latest = self.conversation_store.get_conversation(self.conversation.id)
        if latest is not None:
            self.conversation = latest

        return DesktopTurnResult(
            response=response,
            snapshot=self.snapshot(),
        )

    async def close(self) -> None:
        """Stop background extraction and close local HTTP clients."""
        if self.memory_worker is not None:
            await self.memory_worker.close()
            self.memory_worker = None

        if self.embedding_provider is not None:
            await self.embedding_provider.aclose()
            self.embedding_provider = None

        if self.provider is not None:
            await self.provider.aclose()
            self.provider = None

        self.started = False
