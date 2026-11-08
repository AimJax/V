"""Application services shared by V's desktop interface."""

from __future__ import annotations

import asyncio

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from v.chat import _configured_data_path, build_system_context, load_personality
from v.core.config import load_settings, project_root
from v.core.network import NetworkPolicy
from v.conversations.store import Conversation, ConversationStore
from v.memory.backup import export_backup, import_backup
from v.memory.backfill import (
    MemoryBackfillRunner,
    MemoryBackfillStore,
    MemoryReviewService,
)
from v.memory.embedding_provider import LMStudioEmbeddingProvider
from v.memory.models import Memory
from v.memory.embedding_store import EmbeddingStore
from v.memory.extractor import MemoryExtractor
from v.memory.hybrid_retrieval import HybridMemoryRetriever
from v.memory.queue import ExtractionQueue
from v.memory.retrieval import (
    build_commitment_context,
    build_contextual_memory_query,
    build_memory_context,
    retrieve_relevant_memories,
    select_relevant_commitments,
    source_timestamp_key,
)
from v.memory.store import MemoryStore
from v.memory.continuity import ContinuityStore
from v.memory.worker import MemoryWorker
from v.desktop.settings_store import save_local_desktop_settings
from v.providers.base import ChatMessage
from v.providers.errors import ProviderError, ProviderProtocolError
from v.providers.lm_studio import LMStudioProvider
from v.voice.service import LocalVoiceService
from v.voice.streaming import SpeechTextSegmenter, clean_speech_text
from v.identity import IdentityStore
from v.identity_evolution import IdentityEvolution
from v.cognition import CognitiveStore
from v.interaction import (
    InteractionEvent,
    InteractionEventKind,
    InteractionModality,
)


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    """Data required to render a conversation and its application status."""

    conversation: Conversation
    conversations: list[Conversation]
    messages: list[ChatMessage]
    model: str
    network_mode: str
    semantic_memory_enabled: bool
    voice_enabled: bool = False
    speak_replies: bool = False
    voice_settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DesktopTurnResult:
    """Completed assistant response, optional speech, and session metadata."""

    response: str
    snapshot: DesktopSnapshot
    audio_wav: bytes | None = None
    speech_error: str | None = None
    interaction_event: InteractionEvent | None = None


@dataclass(frozen=True, slots=True)
class DesktopVoiceTurnResult:
    """A transcription, local assistant turn, and optional speech response."""

    transcription: str
    turn: DesktopTurnResult
    audio_wav: bytes | None = None
    speech_error: str | None = None


@dataclass(frozen=True, slots=True)
class DesktopSettingsSnapshot:
    """Editable settings and loaded local model identifiers."""

    model: str
    available_models: list[str]
    temperature: float
    max_tokens: int
    history_messages: int
    offline_mode: bool
    memory_enabled: bool
    automatic_extraction: bool
    retrieval_enabled: bool
    embedding_model: str
    minimum_confidence: float
    idle_delay_seconds: float
    max_jobs_per_idle_cycle: int
    semantic_threshold: float
    retrieval_limit: int
    retrieval_max_characters: int
    personality: str
    personality_path: str
    voice: dict[str, Any] = field(default_factory=dict)


class DesktopService:
    """Own local providers, persistence, memory, and conversation operations."""

    def __init__(self) -> None:
        self.settings: dict = {}
        self.provider: LMStudioProvider | None = None
        self.embedding_provider: LMStudioEmbeddingProvider | None = None
        self.conversation_store: ConversationStore | None = None
        self.memory_store: MemoryStore | None = None
        self.continuity_store: ContinuityStore | None = None
        self.identity_store: IdentityStore | None = None
        self.cognitive_store: CognitiveStore | None = None
        self.identity_context = ''
        self.identity_evolution: IdentityEvolution | None = None
        self._identity_evolution_task: asyncio.Task | None = None
        self.extraction_queue: ExtractionQueue | None = None
        self.memory_worker: MemoryWorker | None = None
        self.memory_backfill_store: MemoryBackfillStore | None = None
        self.memory_backfill_runner: MemoryBackfillRunner | None = None
        self.retriever: HybridMemoryRetriever | None = None
        self.voice_service: LocalVoiceService | None = None
        self.conversation: Conversation | None = None
        self.model = ""
        self.available_models: list[str] = []
        self.network_mode = "UNKNOWN"
        self.history_limit = 24
        self.temperature = 0.7
        self.max_tokens = 512
        self.retrieval_limit = 5
        self.retrieval_max_characters = 2400
        self.personality = ""
        self.started = False
        self._speech_queue: asyncio.Queue | None = None
        self._speech_worker_task: asyncio.Task[None] | None = None
        self._speech_active_task: asyncio.Task[None] | None = None
        self._speech_generation = 0
        self.interaction_events: list[InteractionEvent] = []

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
        self.identity_store = IdentityStore(
            _configured_data_path(self.settings, 'identity_db')
        )
        self.identity_context = self.identity_store.render_context()
        self.cognitive_store = CognitiveStore(
            _configured_data_path(self.settings, "cognition_db")
        )
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
        self.available_models = list(available_models)
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
            self.continuity_store = ContinuityStore(memory_path)
            self.extraction_queue = ExtractionQueue(memory_path)
            self.memory_backfill_store = MemoryBackfillStore(memory_path)

        if self.memory_store is not None and self.extraction_queue is not None:
            extractor = MemoryExtractor(
                self.provider,
                self.conversation_store,
                self.memory_store,
                self.extraction_queue,
                min_confidence=float(
                    memory_settings.get("minimum_confidence", 0.90)
                ),
                conflict_store=self.memory_backfill_store,
                continuity_store=self.continuity_store,
            )
            self.memory_backfill_runner = MemoryBackfillRunner(
                self.conversation_store,
                extractor,
                self.memory_store,
                self.memory_backfill_store,
                batch_size=5,
            )
            if automatic_memory:
                self.memory_worker = MemoryWorker(
                    extractor,
                    idle_delay_seconds=float(
                        memory_settings.get("idle_delay_seconds", 20)
                    ),
                    max_jobs_per_cycle=int(
                        memory_settings.get("max_jobs_per_idle_cycle", 3)
                    ),
                )

        identity_settings = self.settings.get("identity", {})
        if identity_settings.get("automatic_development", True):
            self.identity_evolution = IdentityEvolution(
                self.provider,
                self.conversation_store,
                self.identity_store,
                evaluation_interval_turns=int(
                    identity_settings.get("evaluation_interval_turns", 5)
                ),
                minimum_confidence=float(
                    identity_settings.get("minimum_confidence", 0.78)
                ),
                max_context_characters=int(
                    identity_settings.get("max_context_characters", 8000)
                ),
                max_pending_proposals=int(
                    identity_settings.get("max_pending_proposals", 10)
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
        voice_settings = self.settings.get("voice", {})
        if voice_settings.get("enabled", False) and voice_settings.get(
            "speak_replies", False
        ):
            self._speech_queue = asyncio.Queue()
            self._speech_worker_task = asyncio.create_task(
                self._run_speech_worker()
            )
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
            voice_enabled=bool(self.settings.get("voice", {}).get("enabled", False)),
            speak_replies=bool(self.settings.get("voice", {}).get("speak_replies", False)),
            voice_settings=dict(self.settings.get("voice", {})),
        )

    def new_conversation(self) -> DesktopSnapshot:
        self.interrupt_speech()
        if self.conversation_store is None:
            raise RuntimeError("Desktop service has not started.")

        self.conversation = self.conversation_store.create_conversation()
        return self.snapshot()

    def select_conversation(self, conversation_id: str) -> DesktopSnapshot:
        self.interrupt_speech()
        if self.conversation_store is None:
            raise RuntimeError("Desktop service has not started.")

        conversation = self.conversation_store.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"Conversation not found: {conversation_id}")

        self.conversation = conversation
        return self.snapshot()

    def delete_conversation(self, conversation_id: str) -> DesktopSnapshot:
        """Delete one chat and select a remaining chat or create a fresh one."""
        if self.conversation_store is None:
            raise RuntimeError("Desktop service has not started.")
        if not self.conversation_store.delete_conversation(conversation_id):
            raise KeyError(f"Conversation not found: {conversation_id}")
        if self.conversation is not None and self.conversation.id == conversation_id:
            self.conversation = self.conversation_store.get_latest_conversation()
            if self.conversation is None:
                self.conversation = self.conversation_store.create_conversation()
        return self.snapshot()

    async def send_message(
        self,
        user_text: str,
        on_token: Callable[[str], None],
        on_audio: Callable[[bytes], None] | None = None,
        on_speech_error: Callable[[str], None] | None = None,
        *,
        interaction_event: InteractionEvent | None = None,
        on_interaction_event: Callable[[InteractionEvent], None] | None = None,
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

        event = interaction_event or InteractionEvent.now(
            kind=InteractionEventKind.USER_MESSAGE,
            modality=InteractionModality.TEXT,
            activation_context="typed",
            conversation_id=self.conversation.id,
            content=user_text,
        )
        if event.conversation_id != self.conversation.id:
            raise ValueError("Interaction event belongs to a different conversation.")
        if event.content != user_text:
            raise ValueError("Interaction event content must match the chat message.")
        self.interaction_events.append(event)
        del self.interaction_events[:-100]
        if on_interaction_event is not None:
            on_interaction_event(event)

        self.interrupt_speech()
        speech_generation = self._speech_generation
        voice_settings = self.settings.get("voice", {})
        speech_enabled = (
            self._speech_queue is not None
            and voice_settings.get("enabled", False)
            and voice_settings.get("speak_replies", False)
            and on_audio is not None
        )
        speech_segmenter = SpeechTextSegmenter() if speech_enabled else None

        if self._identity_evolution_task is not None and not self._identity_evolution_task.done():
            self._identity_evolution_task.cancel()
            await asyncio.gather(
                self._identity_evolution_task,
                return_exceptions=True,
            )
        self._identity_evolution_task = None

        if self.memory_worker is not None:
            await self.memory_worker.cancel()

        recent_messages = self.conversation_store.get_recent_messages(
            self.conversation.id,
            self.history_limit,
        )
        retrieval_query = build_contextual_memory_query(
            user_text,
            recent_messages,
        )

        memory_context = None
        salient_memory_ids: tuple[str, ...] = ()
        if self.memory_store is not None and self.settings.get(
            "memory", {}
        ).get("retrieval_enabled", True):
            try:
                if self.retriever is not None:
                    memories = await self.retriever.retrieve(
                        retrieval_query,
                        limit=self.retrieval_limit,
                    )
                else:
                    memories = retrieve_relevant_memories(
                        self.memory_store,
                        retrieval_query,
                        limit=self.retrieval_limit,
                    )
                if self.cognitive_store is not None:
                    memories = self.cognitive_store.prioritize_memories(memories)
                    salient_memory_ids = tuple(memory.id for memory in memories)
                derivation_sources = {}
                temporal_records = {}
                if self.continuity_store is not None:
                    for memory in memories:
                        temporal_records[memory.id] = (
                            self.continuity_store.temporal_record(memory.id)
                        )
                        if memory.memory_type == "inferred_pattern":
                            derivation_sources[memory.id] = (
                                self.continuity_store.derivation_sources(memory.id)
                            )
                memory_context = build_memory_context(
                    memories,
                    max_characters=self.retrieval_max_characters,
                    derivation_sources=derivation_sources,
                    temporal_records=temporal_records,
                )
                if self.continuity_store is not None:
                    commitments = self.continuity_store.list_commitments(
                        state="all", limit=500
                    )
                    selected_commitments = select_relevant_commitments(
                        commitments, retrieval_query
                    )
                    for item in selected_commitments:
                        source_id = item.get("source_memory_id")
                        if source_id:
                            source_memory = self.memory_store.get_memory(source_id)
                            if source_memory is not None:
                                item["source_evidence"] = (
                                    source_memory.evidence or source_memory.content
                                )
                    commitment_context = build_commitment_context(
                        selected_commitments, retrieval_query
                    )
                    if commitment_context:
                        memory_context = (
                            (memory_context + "\n\n") if memory_context else ""
                        ) + commitment_context
            except Exception:
                # Memory failures must never prevent the user from chatting.
                memory_context = None

        cognition_context = (
            self.cognitive_store.render_context(query=user_text)
            if self.cognitive_store is not None else None
        )
        system_content = build_system_context(
            self.personality,
            identity_context=self.identity_context,
            memory_context=memory_context,
            cognition_context=cognition_context,
        )

        messages = [
            ChatMessage(role="system", content=system_content),
            *recent_messages,
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
            if speech_segmenter is not None and self._speech_queue is not None:
                for segment in speech_segmenter.feed(chunk):
                    self._speech_queue.put_nowait(
                        (speech_generation, segment, on_audio, on_speech_error)
                    )

        response = "".join(response_parts)
        if not response:
            raise ProviderProtocolError("LM Studio returned an empty response.")

        if speech_segmenter is not None and self._speech_queue is not None:
            for segment in speech_segmenter.flush():
                self._speech_queue.put_nowait(
                    (speech_generation, segment, on_audio, on_speech_error)
                )

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
        if self.cognitive_store is not None:
            # State transitions are deterministic and derived only from this turn.
            self.cognitive_store.process_turn(
                user_text,
                response,
                conversation_id=self.conversation.id,
                salient_memory_ids=salient_memory_ids,
            )
            self.cognitive_store.reflect()

        if self.extraction_queue is not None:
            self.extraction_queue.enqueue(
                self.conversation.id,
                source_message_id,
            )

        if self.identity_evolution is not None:
            self._identity_evolution_task = asyncio.create_task(
                self._run_identity_evolution()
            )
        elif self.memory_worker is not None:
            await self.memory_worker.schedule()

        latest = self.conversation_store.get_conversation(self.conversation.id)
        if latest is not None:
            self.conversation = latest

        return DesktopTurnResult(
            response=response,
            snapshot=self.snapshot(),
            interaction_event=event,
        )

    async def _run_identity_evolution(self) -> None:
        """Review behavior off the chat path, then resume queued memory work."""
        try:
            if self.identity_evolution is not None:
                await self.identity_evolution.evaluate_if_due()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Identity reflection is optional and must never interrupt conversation.
            pass
        finally:
            if (
                self.memory_worker is not None
                and self.extraction_queue is not None
                and self.extraction_queue.count("pending")
            ):
                await self.memory_worker.schedule()
            self._identity_evolution_task = None

    async def _run_speech_worker(self) -> None:
        """Warm Kokoro once, then synthesize queued segments outside chat generation."""
        voice_service = self._get_voice_service()
        warmup_error: str | None = None
        try:
            await voice_service.warm_up_tts()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            warmup_error = str(error)

        while self._speech_queue is not None:
            item = await self._speech_queue.get()
            if item is None:
                return

            generation, text, on_audio, on_speech_error = item
            if generation != self._speech_generation:
                continue
            if warmup_error is not None:
                if on_speech_error is not None:
                    on_speech_error(warmup_error)
                continue

            active_task = asyncio.create_task(
                self._synthesize_speech_segment(
                    voice_service,
                    generation,
                    text,
                    on_audio,
                    on_speech_error,
                )
            )
            self._speech_active_task = active_task
            try:
                await active_task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            finally:
                if self._speech_active_task is active_task:
                    self._speech_active_task = None

    async def _synthesize_speech_segment(
        self,
        voice_service: LocalVoiceService,
        generation: int,
        text: str,
        on_audio: Callable[[bytes], None],
        on_speech_error: Callable[[str], None] | None,
    ) -> None:
        try:
            speech_text = clean_speech_text(text)
            if not speech_text:
                return

            async for wav_data in voice_service.synthesize_stream(speech_text):
                if generation != self._speech_generation:
                    return
                on_audio(wav_data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if generation == self._speech_generation and on_speech_error is not None:
                on_speech_error(str(error))

    def interrupt_speech(self) -> None:
        """Discard pending speech and cancel the segment currently being synthesized."""
        self._speech_generation += 1
        if self._speech_queue is not None:
            while True:
                try:
                    self._speech_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        active = self._speech_active_task
        if active is not None and not active.done():
            active.cancel()

    def _get_voice_service(self) -> LocalVoiceService:
        voice_settings = self.settings.get("voice", {})
        if not voice_settings.get("enabled", False):
            raise RuntimeError(
                "Voice interaction is disabled. Enable it in V Settings and restart."
            )
        if self.voice_service is None:
            self.voice_service = LocalVoiceService(self.settings)
        return self.voice_service

    async def transcribe_voice(self, wav_data: bytes) -> str:
        """Transcribe one user-recorded WAV through the loopback Whisper server."""
        service = self._get_voice_service()
        result = await service.transcribe(wav_data)
        if not result.text:
            raise ValueError("No speech was recognized. Try speaking closer to the microphone.")
        return result.text

    async def send_voice_message(
        self,
        wav_data: bytes,
        on_token: Callable[[str], None],
        on_audio: Callable[[bytes], None] | None = None,
        on_speech_error: Callable[[str], None] | None = None,
        on_interaction_event: Callable[[InteractionEvent], None] | None = None,
    ) -> DesktopVoiceTurnResult:
        """Transcribe locally and run the normal streaming chat/speech pipeline."""
        transcription = await self.transcribe_voice(wav_data)
        event = InteractionEvent.now(
            kind=InteractionEventKind.SPEECH_TRANSCRIPT,
            modality=InteractionModality.AUDIO,
            activation_context="push_to_talk",
            conversation_id=self.conversation.id if self.conversation else None,
            content=transcription,
        )
        if on_audio is None and on_speech_error is None:
            turn = await self.send_message(
                transcription,
                on_token,
                interaction_event=event,
                on_interaction_event=on_interaction_event,
            )
        else:
            turn = await self.send_message(
                transcription,
                on_token,
                on_audio,
                on_speech_error,
                interaction_event=event,
                on_interaction_event=on_interaction_event,
            )
        return DesktopVoiceTurnResult(
            transcription=transcription,
            turn=turn,
            audio_wav=turn.audio_wav,
            speech_error=turn.speech_error,
        )

    def settings_snapshot(self) -> DesktopSettingsSnapshot:
        """Return current merged settings without exposing unrelated config."""
        if not self.settings or not self.available_models:
            raise RuntimeError("Desktop service has not started.")

        llm = self.settings["llm"]
        memory = self.settings.get("memory", {})
        privacy = self.settings.get("privacy", {})
        paths = self.settings.get("paths", {})

        personality_path = Path(paths.get("personality", "config/personality.md"))
        if not personality_path.is_absolute():
            personality_path = project_root() / personality_path

        return DesktopSettingsSnapshot(
            model=self.model,
            available_models=list(self.available_models),
            temperature=float(llm.get("temperature", 0.7)),
            max_tokens=int(llm.get("max_tokens", 512)),
            history_messages=int(llm.get("history_messages", 24)),
            offline_mode=bool(privacy.get("offline_mode", False)),
            memory_enabled=bool(memory.get("enabled", True)),
            automatic_extraction=bool(
                memory.get("automatic_extraction", True)
            ),
            retrieval_enabled=bool(memory.get("retrieval_enabled", True)),
            embedding_model=str(
                memory.get(
                    "embedding_model",
                    "text-embedding-nomic-embed-text-v1.5",
                )
            ),
            minimum_confidence=float(
                memory.get("minimum_confidence", 0.90)
            ),
            idle_delay_seconds=float(
                memory.get("idle_delay_seconds", 20)
            ),
            max_jobs_per_idle_cycle=int(
                memory.get("max_jobs_per_idle_cycle", 3)
            ),
            semantic_threshold=float(
                memory.get("semantic_threshold", 0.60)
            ),
            retrieval_limit=int(memory.get("retrieval_limit", 5)),
            retrieval_max_characters=int(
                memory.get("retrieval_max_characters", 2400)
            ),
            personality=self.personality,
            personality_path=str(personality_path),
            voice=dict(self.settings.get("voice", {})),
        )

    def save_desktop_settings(
        self,
        changes: dict,
        personality: str,
    ) -> str:
        """Persist validated settings locally; running services restart to apply."""
        if not self.settings or not self.available_models:
            raise RuntimeError("Desktop service has not started.")

        local_path, personality_path = save_local_desktop_settings(
            self.settings,
            changes,
            personality,
            available_models=self.available_models,
        )
        return (
            f"Saved local settings to {local_path} and personality to "
            f"{personality_path}. Restart V to apply the changes."
        )

    def list_memories(
        self,
        query: str = "",
        memory_type: str = "",
        provenance: str = "",
    ) -> list[Memory]:
        """Search and filter the local memory database for the manager."""
        if self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")

        if query.strip():
            memories = self.memory_store.search_memories_any(
                query.strip(),
                limit=1000,
            )
        else:
            memories = self.memory_store.list_memories(limit=1000)

        if memory_type:
            memories = [
                memory for memory in memories
                if memory.memory_type == memory_type
            ]

        if provenance:
            memories = [
                memory for memory in memories
                if memory.provenance == provenance
            ]

        return memories


    def create_identity_proposal(self, category: str, description: str):
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        return self.identity_store.create_proposal(
            category=category,
            description=description,
            rationale="Explicitly proposed by the user in Identity Manager.",
            evidence_refs=[],
            confidence=1.0,
            origin="user_stated",
        )

    def export_identity(self, destination: str, *, overwrite: bool = False) -> str:
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        path = self.identity_store.export_backup(destination, overwrite=overwrite)
        return f"Exported V's identity backup to {path}. The JSON file is unencrypted."

    def import_identity(self, source: str) -> str:
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        snapshot = self.identity_store.import_backup(source, replace=True)
        self.identity_context = self.identity_store.render_context()
        return f"Restored V's identity revision {snapshot.revision} from the selected backup."

    def identity_snapshot(self):
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        return self.identity_store.get_snapshot()

    def identity_revisions(self):
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        return self.identity_store.list_revisions()

    def identity_proposals(self, status: str = "pending"):
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        return self.identity_store.list_proposals(status=status)

    def review_identity_proposal(self, proposal_id: str, decision: str):
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        proposal = self.identity_store.review_proposal(
            proposal_id,
            decision=decision,
        )
        self.identity_context = self.identity_store.render_context()
        return proposal

    def update_identity_trait(self, trait_id: str, changes: dict):
        if self.identity_store is None:
            raise RuntimeError("Identity service is not available.")
        trait = self.identity_store.update_trait(
            trait_id,
            allow_foundational=True,
            **changes,
        )
        self.identity_context = self.identity_store.render_context()
        return trait

    async def run_memory_backfill(
        self,
        *,
        new_run: bool = False,
        on_progress: Callable[[dict], None] | None = None,
    ) -> dict:
        if self.memory_backfill_runner is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        if self.memory_worker is not None:
            await self.memory_worker.cancel()
        return await self.memory_backfill_runner.run(
            new_run=new_run,
            on_progress=on_progress,
        )

    def memory_backfill_status(self) -> dict | None:
        if self.memory_backfill_runner is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.memory_backfill_runner.status()

    def list_memory_review_candidates(
        self,
        *,
        status: str = "pending",
        limit: int = 100,
    ) -> list[dict]:
        if self.memory_backfill_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.memory_backfill_store.list_candidates(
            status=status,
            limit=limit,
        )

    def approve_memory_candidate(
        self,
        candidate_id: str,
        changes: dict | None = None,
    ) -> Memory:
        if self.memory_store is None or self.memory_backfill_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return MemoryReviewService(
            self.memory_store,
            self.memory_backfill_store,
        ).approve_candidate(candidate_id, changes=changes)

    def reject_memory_candidate(
        self,
        candidate_id: str,
        reason: str = "",
    ) -> None:
        if self.memory_store is None or self.memory_backfill_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        MemoryReviewService(
            self.memory_store,
            self.memory_backfill_store,
        ).reject_candidate(candidate_id, reason=reason)

    def update_memory(
        self,
        memory_id: str,
        changes: dict,
    ) -> Memory:
        """Apply an explicit correction while preserving source references."""
        if self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")

        if not isinstance(changes, dict) or not changes:
            raise ValueError("At least one memory field correction is required.")

        allowed = {
            "memory_type",
            "subject",
            "content",
            "memory_key",
            "confidence",
            "importance",
            "evidence",
        }
        unexpected = set(changes) - allowed
        if unexpected:
            raise ValueError(
                f"Unsupported memory fields: {sorted(unexpected)}"
            )

        return self.memory_store.update_memory(memory_id, **changes)

    def confirm_memory(self, memory_id: str) -> Memory:
        """Record the user's explicit re-confirmation of one saved memory."""
        if self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.memory_store.confirm_memory(memory_id)

    def delete_memory(self, memory_id: str) -> bool:
        """Permanently delete one memory record."""
        if self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")

        return self.memory_store.delete_memory(memory_id)

    def export_memories(
        self,
        destination: str,
        *,
        overwrite: bool = False,
    ) -> str:
        """Export a versioned plaintext JSON memory backup."""
        if self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")

        path, count = export_backup(
            self.memory_store,
            destination,
            overwrite=overwrite,
        )
        return (
            f"Exported {count} memory record(s) to {path}. "
            "This JSON backup is unencrypted."
        )

    def import_memories(self, source: str) -> str:
        """Merge a validated backup without overwriting existing memories."""
        if self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")

        restored, skipped = import_backup(self.memory_store, source)
        return (
            f"Restored {restored} record(s); skipped {skipped} identical record(s). "
            "Existing memories were not overwritten or deleted."
        )

    async def cancel_background_model_work(self) -> None:
        """Yield the configured local model to an interactive memory operation."""
        task = self._identity_evolution_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._identity_evolution_task = None
        if self.memory_worker is not None:
            await self.memory_worker.cancel()

    async def preview_memory_context(self, query: str) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Enter a query to preview memory retrieval.")
        if self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        if not self.settings.get("memory", {}).get("retrieval_enabled", True):
            return {
                "query": query,
                "retrieval_query": query,
                "memories": [],
                "commitments": [],
                "context": None,
                "semantic": False,
                "fallback_reason": "Memory retrieval is disabled.",
            }

        recent_messages = (
            self.conversation_store.get_recent_messages(
                self.conversation.id,
                self.history_limit,
            )
            if self.conversation is not None
            else []
        )
        retrieval_query = build_contextual_memory_query(query, recent_messages)

        if self.retriever is not None:
            memories = await self.retriever.retrieve(
                retrieval_query,
                limit=self.retrieval_limit,
            )
            semantic = True
            fallback_reason = self.retriever.last_fallback_reason
        else:
            memories = retrieve_relevant_memories(
                self.memory_store,
                retrieval_query,
                limit=self.retrieval_limit,
            )
            semantic = False
            fallback_reason = None

        derivation_sources = {}
        temporal_records = {}
        if self.continuity_store is not None:
            for memory in memories:
                temporal_records[memory.id] = (
                    self.continuity_store.temporal_record(memory.id)
                )
                if memory.memory_type == "inferred_pattern":
                    derivation_sources[memory.id] = (
                        self.continuity_store.derivation_sources(memory.id)
                    )
        context = build_memory_context(
            memories,
            max_characters=self.retrieval_max_characters,
            derivation_sources=derivation_sources,
            temporal_records=temporal_records,
        )
        commitments = (
            self.continuity_store.list_commitments(state="all", limit=500)
            if self.continuity_store is not None
            else []
        )
        selected_commitments = select_relevant_commitments(commitments, retrieval_query)
        for item in selected_commitments:
            source_id = item.get("source_memory_id")
            if source_id and self.memory_store is not None:
                source_memory = self.memory_store.get_memory(source_id)
                if source_memory is not None:
                    item["source_evidence"] = (
                        source_memory.evidence or source_memory.content
                    )
        commitment_context = build_commitment_context(
            selected_commitments, retrieval_query
        )
        if commitment_context:
            context = ((context + "\n\n") if context else "") + commitment_context
        return {
            "query": query,
            "retrieval_query": retrieval_query,
            "memories": [
                {
                    "memory_id": memory.id,
                    "memory_type": memory.memory_type,
                    "subject": memory.subject,
                    "content": memory.content,
                    "provenance": memory.provenance,
                    "confidence": memory.confidence,
                    "source_created_at": memory.source_created_at,
                    "temporal_state": (
                        temporal_records[memory.id]["state"]
                        if temporal_records.get(memory.id, {}).get("recorded_at")
                        else "unspecified"
                    ),
                    "valid_from": temporal_records.get(memory.id, {}).get("valid_from"),
                    "valid_until": temporal_records.get(memory.id, {}).get("valid_until"),
                }
                for memory in memories
            ],
            "context": context,
            "commitments": [
                {
                    "title": item["title"],
                    "description": item["description"],
                    "due_at": item["due_at"],
                    "state": item["state"],
                    "source_memory_id": item["source_memory_id"],
                    "source_evidence": item.get("source_evidence"),
                }
                for item in selected_commitments
            ],
            "semantic": semantic,
            "fallback_reason": fallback_reason,
        }

    async def run_memory_consolidation(self, *, limit: int = 3, cancel_event=None):
        if (
            self.memory_store is None
            or self.continuity_store is None
            or self.provider is None
        ):
            raise RuntimeError("Local memory consolidation is not available.")
        from v.memory.consolidation import MemoryConsolidator

        return await MemoryConsolidator(
            self.provider,
            self.memory_store,
            self.continuity_store,
        ).run(limit=limit, cancel_event=cancel_event)

    def memory_continuity_snapshot(self, memory_id: str) -> dict:
        if self.continuity_store is None or self.memory_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        selected = self.memory_store.get_memory(memory_id)
        if selected is None:
            raise KeyError(memory_id)
        if selected.memory_key:
            related = [
                item
                for item in self.memory_store.list_memories(limit=10_000)
                if item.subject.casefold() == selected.subject.casefold()
                and item.memory_key == selected.memory_key
            ]
        elif selected.subject.strip():
            related = [
                item
                for item in self.memory_store.list_memories(limit=10_000)
                if item.subject.casefold() == selected.subject.casefold()
                and item.memory_type == selected.memory_type
            ]
        else:
            related = [selected]
        related.sort(
            key=lambda item: source_timestamp_key(
                item.source_created_at or item.created_at
            )
        )
        timeline = []
        for item in related[-100:]:
            temporal = self.continuity_store.temporal_record(item.id)
            timeline.append({
                "memory_id": item.id,
                "memory_type": item.memory_type,
                "provenance": item.provenance,
                "source_date": item.source_created_at or item.created_at,
                "date_basis": (
                    "source timestamp" if item.source_created_at else "record creation time"
                ),
                "temporal_state": (
                    temporal["state"] if temporal.get("recorded_at") else "unspecified"
                ),
                "valid_from": temporal.get("valid_from"),
                "valid_until": temporal.get("valid_until"),
                "content": item.content[:220],
            })
        return {
            "memory_id": memory_id,
            "temporal": self.continuity_store.temporal_record(memory_id),
            "timeline": timeline,
            "derivation_sources": self.continuity_store.derivation_sources(memory_id),
            "commitments": self.continuity_store.list_commitments(state="all", limit=500),
        }

    def update_memory_temporal_record(self, memory_id: str, state: str, **fields) -> dict:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.continuity_store.update_temporal_record(
            memory_id, state, **fields
        )

    def ensure_memory_temporal_record(self, memory_id: str, **fields) -> dict:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.continuity_store.ensure_temporal_record(memory_id, **fields)

    def list_memory_commitments(self, *, state: str = "open", limit: int = 100) -> list[dict]:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.continuity_store.list_commitments(state=state, limit=limit)

    def create_memory_commitment(self, title: str, **fields) -> dict:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.continuity_store.create_commitment(title, **fields)

    def update_memory_commitment(
        self,
        commitment_id: str,
        state: str | None = None,
        *,
        title: str | None = None,
        description: str | None = None,
        due_at: str | None | object = ..., 
    ) -> dict:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        changes = {"title": title, "description": description}
        if due_at is not ...:
            changes["due_at"] = due_at
        return self.continuity_store.update_commitment(
            commitment_id, state, **changes
        )

    def set_memory_temporal_state(self, memory_id: str, state: str, **fields) -> dict:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.continuity_store.set_memory_state(memory_id, state, **fields)

    def memory_derivation_sources(self, memory_id: str) -> list[dict]:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.continuity_store.derivation_sources(memory_id)

    def review_memory_derivation(self, memory_id: str, decision: str) -> int:
        if self.continuity_store is None:
            raise RuntimeError("Long-term memory is disabled in configuration.")
        return self.continuity_store.review_derivation(memory_id, decision)

    async def close(self) -> None:
        """Stop background workers and close local clients."""
        if self._identity_evolution_task is not None:
            self._identity_evolution_task.cancel()
            await asyncio.gather(
                self._identity_evolution_task,
                return_exceptions=True,
            )
            self._identity_evolution_task = None

        if self._speech_worker_task is not None:
            self.interrupt_speech()
            if self._speech_queue is not None:
                self._speech_queue.put_nowait(None)
            await asyncio.gather(
                self._speech_worker_task,
                return_exceptions=True,
            )
            self._speech_worker_task = None
            self._speech_queue = None

        if self.voice_service is not None:
            await self.voice_service.close()
            self.voice_service = None

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
