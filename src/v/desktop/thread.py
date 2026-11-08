"""Qt thread hosting V's persistent asynchronous local runtime."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QThread, Signal

from v.desktop.service import (
    DesktopService,
    DesktopSnapshot,
    DesktopTurnResult,
    DesktopVoiceTurnResult,
)


class DesktopRuntimeThread(QThread):
    """Keep async model, memory, and SQLite work off the GUI thread."""

    ready = Signal(object)
    startup_failed = Signal(str)
    token_received = Signal(str)
    speech_audio_ready = Signal(bytes)
    speech_failed = Signal(str)
    turn_completed = Signal(object)
    voice_turn_completed = Signal(object)
    operation_failed = Signal(str)
    session_changed = Signal(object)
    memory_list_ready = Signal(object)
    memory_updated = Signal(object)
    memory_confirmed = Signal(object)
    memory_deleted = Signal(str)
    memory_backup_completed = Signal(str)
    memory_operation_failed = Signal(str)
    memory_continuity_ready = Signal(object)
    memory_continuity_failed = Signal(str)
    memory_consolidation_completed = Signal(object)
    memory_consolidation_failed = Signal(str)
    memory_consolidation_cancelled = Signal()
    memory_context_preview_ready = Signal(object)
    memory_context_preview_failed = Signal(str)
    memory_context_preview_cancelled = Signal()
    memory_backfill_progress = Signal(object)
    memory_backfill_completed = Signal(object)
    memory_backfill_paused = Signal()
    memory_backfill_failed = Signal(str)
    memory_review_ready = Signal(object)
    memory_review_changed = Signal()
    settings_ready = Signal(object)
    settings_saved = Signal(str)
    settings_operation_failed = Signal(str)
    identity_ready = Signal(object, object, object)
    identity_failed = Signal(str)
    identity_changed = Signal()
    identity_backup_completed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._commands: asyncio.Queue | None = None
        self._active_task: asyncio.Task | None = None
        self._backfill_task: asyncio.Task | None = None
        self._consolidation_task: asyncio.Task | None = None
        self._consolidation_cancel_event: asyncio.Event | None = None
        self._context_preview_task: asyncio.Task | None = None
        self._shutdown_requested = False
        self._memory_filters = ("", "", "")

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._serve())
        except Exception as error:
            self.startup_failed.emit(str(error))
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )

            loop.close()
            self._loop = None
            self._commands = None
            self._active_task = None
            self._backfill_task = None

    async def _cancel_backfill(self) -> None:
        task = self._backfill_task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cancel_consolidation(self) -> None:
        task = self._consolidation_task
        if task is None or task.done():
            self._consolidation_task = None
            self._consolidation_cancel_event = None
            return
        if self._consolidation_cancel_event is not None:
            self._consolidation_cancel_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._consolidation_task = None
        self._consolidation_cancel_event = None
        self.memory_consolidation_cancelled.emit()

    async def _cancel_context_preview(self) -> None:
        task = self._context_preview_task
        if task is None or task.done():
            self._context_preview_task = None
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._context_preview_task = None
        self.memory_context_preview_cancelled.emit()

    async def _serve(self) -> None:
        service = DesktopService()

        try:
            snapshot = await service.start()
        except Exception as error:
            await service.close()
            self.startup_failed.emit(str(error))
            return

        self._commands = asyncio.Queue()

        if self._shutdown_requested:
            await service.close()
            return

        self.ready.emit(snapshot)

        while True:
            command, payload = await self._commands.get()

            if command == "shutdown":
                await self._cancel_backfill()
                await self._cancel_consolidation()
                await self._cancel_context_preview()
                break

            if command == "send":
                await self._cancel_backfill()
                await self._cancel_consolidation()
                await self._cancel_context_preview()
                self._active_task = asyncio.create_task(
                    service.send_message(
                        payload,
                        self.token_received.emit,
                        self.speech_audio_ready.emit,
                        self.speech_failed.emit,
                    )
                )
                try:
                    result: DesktopTurnResult = await self._active_task
                    self.turn_completed.emit(result)
                except asyncio.CancelledError:
                    # Shutdown interrupted the in-flight HTTP stream.
                    pass
                except Exception as error:
                    self.operation_failed.emit(str(error))
                finally:
                    self._active_task = None
                continue

            if command == "voice_turn":
                await self._cancel_backfill()
                await self._cancel_consolidation()
                await self._cancel_context_preview()
                self._active_task = asyncio.create_task(
                    service.send_voice_message(
                        payload,
                        self.token_received.emit,
                        self.speech_audio_ready.emit,
                        self.speech_failed.emit,
                    )
                )
                try:
                    result: DesktopVoiceTurnResult = await self._active_task
                    self.voice_turn_completed.emit(result)
                except asyncio.CancelledError:
                    pass
                except Exception as error:
                    self.operation_failed.emit(str(error))
                finally:
                    self._active_task = None
                continue

            if command == "speech_stop":
                service.interrupt_speech()
                continue

            if command == "new":
                try:
                    self.session_changed.emit(service.new_conversation())
                except Exception as error:
                    self.operation_failed.emit(str(error))
                continue

            if command == "delete_conversation":
                try:
                    self.session_changed.emit(
                        service.delete_conversation(str(payload))
                    )
                except Exception as error:
                    self.operation_failed.emit(str(error))
                continue

            if command == "select":
                try:
                    self.session_changed.emit(
                        service.select_conversation(str(payload))
                    )
                except Exception as error:
                    self.operation_failed.emit(str(error))
                continue

            if command == "identity_export":
                try:
                    destination, overwrite = payload
                    self.identity_backup_completed.emit(
                        service.export_identity(destination, overwrite=overwrite)
                    )
                except Exception as error:
                    self.identity_failed.emit(str(error))
                continue

            if command == "identity_import":
                try:
                    self.identity_backup_completed.emit(
                        service.import_identity(str(payload))
                    )
                    self.identity_ready.emit(
                        service.identity_snapshot(),
                        service.identity_proposals(),
                        service.identity_revisions(),
                    )
                except Exception as error:
                    self.identity_failed.emit(str(error))
                continue

            if command == "identity_get":
                try:
                    self.identity_ready.emit(
                        service.identity_snapshot(),
                        service.identity_proposals(),
                        service.identity_revisions(),
                    )
                except Exception as error:
                    self.identity_failed.emit(str(error))
                continue

            if command == "identity_review":
                try:
                    proposal_id, decision = payload
                    service.review_identity_proposal(proposal_id, decision)
                    self.identity_changed.emit()
                    self.identity_ready.emit(
                        service.identity_snapshot(),
                        service.identity_proposals(),
                        service.identity_revisions(),
                    )
                except Exception as error:
                    self.identity_failed.emit(str(error))
                continue

            if command == "identity_update":
                try:
                    trait_id, changes = payload
                    service.update_identity_trait(trait_id, changes)
                    self.identity_changed.emit()
                    self.identity_ready.emit(
                        service.identity_snapshot(),
                        service.identity_proposals(),
                        service.identity_revisions(),
                    )
                except Exception as error:
                    self.identity_failed.emit(str(error))
                continue

            if command == "identity_propose":
                try:
                    category, description = payload
                    service.create_identity_proposal(category, description)
                    self.identity_ready.emit(
                        service.identity_snapshot(),
                        service.identity_proposals(),
                        service.identity_revisions(),
                    )
                except Exception as error:
                    self.identity_failed.emit(str(error))
                continue

            if command == "settings_get":
                try:
                    self.settings_ready.emit(service.settings_snapshot())
                except Exception as error:
                    self.settings_operation_failed.emit(str(error))
                continue

            if command == "settings_save":
                try:
                    changes, personality = payload
                    message = service.save_desktop_settings(
                        changes,
                        personality,
                    )
                    self.settings_saved.emit(message)
                except Exception as error:
                    self.settings_operation_failed.emit(str(error))
                continue

            if command == "memory_backfill_start":
                if self._backfill_task is not None and not self._backfill_task.done():
                    self.memory_backfill_failed.emit(
                        "A historical memory scan is already running."
                    )
                    continue

                async def run_backfill(new_run: bool) -> None:
                    try:
                        result = await service.run_memory_backfill(
                            new_run=new_run,
                            on_progress=self.memory_backfill_progress.emit,
                        )
                    except asyncio.CancelledError:
                        self.memory_backfill_paused.emit()
                        raise
                    except Exception as error:
                        self.memory_backfill_failed.emit(str(error))
                    else:
                        self.memory_backfill_completed.emit(result)
                    finally:
                        self._backfill_task = None
                        if (
                            service.memory_worker is not None
                            and service.extraction_queue is not None
                            and service.extraction_queue.count("pending")
                        ):
                            await service.memory_worker.schedule()

                self._backfill_task = asyncio.create_task(
                    run_backfill(bool(payload))
                )
                continue

            if command == "memory_backfill_cancel":
                await self._cancel_backfill()
                continue

            if command == "memory_backfill_status":
                try:
                    self.memory_backfill_progress.emit(
                        service.memory_backfill_status() or {"status": "not_started"}
                    )
                except Exception as error:
                    self.memory_backfill_failed.emit(str(error))
                continue

            if command == "memory_review_list":
                try:
                    status, limit = payload
                    self.memory_review_ready.emit(
                        service.list_memory_review_candidates(
                            status=status,
                            limit=limit,
                        )
                    )
                except Exception as error:
                    self.memory_backfill_failed.emit(str(error))
                continue

            if command == "memory_review_approve":
                try:
                    candidate_id, changes = payload
                    service.approve_memory_candidate(candidate_id, changes)
                    self.memory_review_changed.emit()
                    self.memory_review_ready.emit(
                        service.list_memory_review_candidates(status="pending")
                    )
                    # Keep the main Memory Manager table in sync with approvals.
                    self.memory_list_ready.emit(service.list_memories())
                except Exception as error:
                    self.memory_backfill_failed.emit(str(error))
                continue

            if command == "memory_review_reject":
                try:
                    candidate_id, reason = payload
                    service.reject_memory_candidate(candidate_id, reason)
                    self.memory_review_changed.emit()
                    self.memory_review_ready.emit(
                        service.list_memory_review_candidates(status="pending")
                    )
                except Exception as error:
                    self.memory_backfill_failed.emit(str(error))
                continue

            if command == "memory_context_preview":
                if (
                    self._context_preview_task is not None
                    and not self._context_preview_task.done()
                ):
                    await self._cancel_context_preview()
                if (
                    self._consolidation_task is not None
                    and not self._consolidation_task.done()
                ) or (
                    self._backfill_task is not None
                    and not self._backfill_task.done()
                ):
                    self.memory_context_preview_failed.emit(
                        "Wait for other memory jobs to finish before previewing recall."
                    )
                    continue
                await service.cancel_background_model_work()

                async def run_context_preview() -> None:
                    try:
                        result = await service.preview_memory_context(str(payload))
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        self.memory_context_preview_failed.emit(str(error))
                    else:
                        self.memory_context_preview_ready.emit(result)
                    finally:
                        self._context_preview_task = None
                        if (
                            service.memory_worker is not None
                            and service.extraction_queue is not None
                            and service.extraction_queue.count("pending")
                        ):
                            await service.memory_worker.schedule()

                self._context_preview_task = asyncio.create_task(run_context_preview())
                continue

            if command == "memory_context_preview_cancel":
                await self._cancel_context_preview()
                continue

            if command == "memory_consolidate_start":
                if (
                    self._consolidation_task is not None
                    and not self._consolidation_task.done()
                ):
                    self.memory_consolidation_failed.emit(
                        "A memory consolidation job is already running."
                    )
                    continue
                if self._backfill_task is not None and not self._backfill_task.done():
                    self.memory_consolidation_failed.emit(
                        "Wait for the historical memory scan to finish before consolidating."
                    )
                    continue
                if (
                    self._context_preview_task is not None
                    and not self._context_preview_task.done()
                ):
                    self.memory_consolidation_failed.emit(
                        "Wait for the memory-context preview to finish before consolidating."
                    )
                    continue
                await service.cancel_background_model_work()
                cancel_event = asyncio.Event()
                self._consolidation_cancel_event = cancel_event

                async def run_consolidation() -> None:
                    try:
                        report = await service.run_memory_consolidation(
                            limit=3,
                            cancel_event=cancel_event,
                        )
                    except asyncio.CancelledError:
                        return
                    except Exception as error:
                        self.memory_consolidation_failed.emit(str(error))
                    else:
                        self.memory_consolidation_completed.emit(report)
                        query, memory_type, provenance = self._memory_filters
                        self.memory_list_ready.emit(
                            service.list_memories(
                                query=query,
                                memory_type=memory_type,
                                provenance=provenance,
                            )
                        )
                    finally:
                        self._consolidation_task = None
                        self._consolidation_cancel_event = None
                        if (
                            service.memory_worker is not None
                            and service.extraction_queue is not None
                            and service.extraction_queue.count("pending")
                        ):
                            await service.memory_worker.schedule()

                self._consolidation_task = asyncio.create_task(run_consolidation())
                continue

            if command == "memory_consolidate_cancel":
                await self._cancel_consolidation()
                if (
                    service.memory_worker is not None
                    and service.extraction_queue is not None
                    and service.extraction_queue.count("pending")
                ):
                    await service.memory_worker.schedule()
                continue

            if command == "memory_continuity_get":
                try:
                    self.memory_continuity_ready.emit(
                        service.memory_continuity_snapshot(str(payload))
                    )
                except Exception as error:
                    self.memory_continuity_failed.emit(str(error))
                continue

            if command == "memory_continuity_state":
                try:
                    memory_id, state, replacement, note, valid_from, valid_until = payload
                    service.update_memory_temporal_record(
                        memory_id,
                        state,
                        valid_from=valid_from or None,
                        valid_until=valid_until or None,
                        superseded_by=replacement or None,
                        note=note,
                    )
                    self.memory_continuity_ready.emit(
                        service.memory_continuity_snapshot(memory_id)
                    )
                except Exception as error:
                    self.memory_continuity_failed.emit(str(error))
                continue

            if command == "memory_derivation_review":
                try:
                    memory_id, decision = payload
                    service.review_memory_derivation(memory_id, decision)
                    self.memory_continuity_ready.emit(
                        service.memory_continuity_snapshot(memory_id)
                    )
                except Exception as error:
                    self.memory_continuity_failed.emit(str(error))
                continue

            if command == "memory_commitment_create":
                try:
                    title, description, due_at, memory_id = payload
                    service.create_memory_commitment(
                        title,
                        description=description,
                        due_at=due_at or None,
                        source_memory_id=memory_id or None,
                    )
                    self.memory_continuity_ready.emit(
                        service.memory_continuity_snapshot(memory_id)
                    )
                except Exception as error:
                    self.memory_continuity_failed.emit(str(error))
                continue

            if command == "memory_commitment_update":
                try:
                    commitment_id, state, memory_id = payload
                    service.update_memory_commitment(commitment_id, state)
                    self.memory_continuity_ready.emit(
                        service.memory_continuity_snapshot(memory_id)
                    )
                except Exception as error:
                    self.memory_continuity_failed.emit(str(error))
                continue

            if command == "memory_commitment_edit":
                try:
                    commitment_id, title, description, due_at, memory_id = payload
                    service.update_memory_commitment(
                        commitment_id,
                        title=title,
                        description=description,
                        due_at=due_at or None,
                    )
                    self.memory_continuity_ready.emit(
                        service.memory_continuity_snapshot(memory_id)
                    )
                except Exception as error:
                    self.memory_continuity_failed.emit(str(error))
                continue

            if command == "memory_list":
                try:
                    query, memory_type, provenance = payload
                    memories = service.list_memories(
                        query=query,
                        memory_type=memory_type,
                        provenance=provenance,
                    )
                    self.memory_list_ready.emit(memories)
                except Exception as error:
                    self.memory_operation_failed.emit(str(error))
                continue

            if command == "memory_update":
                try:
                    memory_id, changes = payload
                    memory = service.update_memory(memory_id, changes)
                    self.memory_updated.emit(memory)
                except Exception as error:
                    self.memory_operation_failed.emit(str(error))
                continue

            if command == "memory_confirm":
                try:
                    memory = service.confirm_memory(str(payload))
                    self.memory_confirmed.emit(memory)
                except Exception as error:
                    self.memory_operation_failed.emit(str(error))
                continue

            if command == "memory_delete":
                try:
                    deleted = service.delete_memory(str(payload))
                    if not deleted:
                        raise KeyError(f"Memory not found: {payload}")
                    self.memory_deleted.emit(str(payload))
                except Exception as error:
                    self.memory_operation_failed.emit(str(error))
                continue

            if command == "memory_export":
                try:
                    destination, overwrite = payload
                    message = service.export_memories(
                        destination,
                        overwrite=overwrite,
                    )
                    self.memory_backup_completed.emit(message)
                except Exception as error:
                    self.memory_operation_failed.emit(str(error))
                continue

            if command == "memory_import":
                try:
                    message = service.import_memories(str(payload))
                    query, memory_type, provenance = self._memory_filters
                    memories = service.list_memories(
                        query=query,
                        memory_type=memory_type,
                        provenance=provenance,
                    )
                    self.memory_list_ready.emit(memories)
                    self.memory_backup_completed.emit(message)
                except Exception as error:
                    self.memory_operation_failed.emit(str(error))
                continue

        await service.close()

    def _post(self, command: str, payload: object = None) -> None:
        loop = self._loop
        if loop is None:
            return

        def enqueue() -> None:
            if self._commands is not None:
                self._commands.put_nowait((command, payload))

        loop.call_soon_threadsafe(enqueue)

    def send_message(self, text: str) -> None:
        self._post("send", text)

    def send_voice_turn(self, wav_data: bytes) -> None:
        self._post("voice_turn", wav_data)

    def interrupt_speech(self) -> None:
        self._post("speech_stop")

    def new_conversation(self) -> None:
        self._post("new")

    def select_conversation(self, conversation_id: str) -> None:
        self._post("select", conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        self._post("delete_conversation", conversation_id)


    def export_identity(self, destination: str, overwrite: bool = False) -> None:
        self._post("identity_export", (destination, overwrite))

    def import_identity(self, source: str) -> None:
        self._post("identity_import", source)

    def get_identity(self) -> None:
        self._post("identity_get")

    def review_identity_proposal(self, proposal_id: str, decision: str) -> None:
        self._post("identity_review", (proposal_id, decision))

    def update_identity_trait(self, trait_id: str, changes: dict) -> None:
        self._post("identity_update", (trait_id, changes))

    def propose_identity_trait(self, category: str, description: str) -> None:
        self._post("identity_propose", (category, description))

    def get_settings(self) -> None:
        self._post("settings_get")

    def save_settings(self, changes: dict, personality: str) -> None:
        self._post("settings_save", (changes, personality))

    def preview_memory_context(self, query: str) -> None:
        self._post("memory_context_preview", query)

    def cancel_memory_context_preview(self) -> None:
        self._post("memory_context_preview_cancel")

    def start_memory_consolidation(self) -> None:
        self._post("memory_consolidate_start")

    def cancel_memory_consolidation(self) -> None:
        self._post("memory_consolidate_cancel")

    def get_memory_continuity(self, memory_id: str) -> None:
        self._post("memory_continuity_get", memory_id)

    def update_memory_temporal_state(
        self,
        memory_id: str,
        state: str,
        replacement: str,
        note: str,
        valid_from: str,
        valid_until: str,
    ) -> None:
        self._post(
            "memory_continuity_state",
            (memory_id, state, replacement, note, valid_from, valid_until),
        )

    def review_memory_derivation(self, memory_id: str, decision: str) -> None:
        self._post("memory_derivation_review", (memory_id, decision))

    def create_memory_commitment(
        self, title: str, description: str, due_at: str, memory_id: str,
    ) -> None:
        self._post(
            "memory_commitment_create",
            (title, description, due_at, memory_id),
        )

    def update_memory_commitment(
        self, commitment_id: str, state: str, memory_id: str,
    ) -> None:
        self._post(
            "memory_commitment_update",
            (commitment_id, state, memory_id),
        )

    def edit_memory_commitment(
        self,
        commitment_id: str,
        title: str,
        description: str,
        due_at: str,
        memory_id: str,
    ) -> None:
        self._post(
            "memory_commitment_edit",
            (commitment_id, title, description, due_at, memory_id),
        )

    def list_memories(
        self,
        query: str = "",
        memory_type: str = "",
        provenance: str = "",
    ) -> None:
        self._memory_filters = (query, memory_type, provenance)
        self._post("memory_list", self._memory_filters)

    def start_memory_backfill(self, *, new_run: bool = False) -> None:
        self._post("memory_backfill_start", new_run)

    def cancel_memory_backfill(self) -> None:
        self._post("memory_backfill_cancel")

    def get_memory_backfill_status(self) -> None:
        self._post("memory_backfill_status")

    def list_memory_review_candidates(
        self,
        *,
        status: str = "pending",
        limit: int = 100,
    ) -> None:
        self._post("memory_review_list", (status, limit))

    def approve_memory_candidate(
        self,
        candidate_id: str,
        changes: dict | None = None,
    ) -> None:
        self._post("memory_review_approve", (candidate_id, changes or {}))

    def reject_memory_candidate(
        self,
        candidate_id: str,
        reason: str = "",
    ) -> None:
        self._post("memory_review_reject", (candidate_id, reason))

    def update_memory(self, memory_id: str, changes: dict) -> None:
        self._post("memory_update", (memory_id, changes))

    def confirm_memory(self, memory_id: str) -> None:
        self._post("memory_confirm", memory_id)

    def delete_memory(self, memory_id: str) -> None:
        self._post("memory_delete", memory_id)

    def export_memories(self, destination: str, *, overwrite: bool = False) -> None:
        self._post("memory_export", (destination, overwrite))

    def import_memories(self, source: str) -> None:
        self._post("memory_import", source)

    def request_shutdown(self) -> None:
        """Cancel active generation and close services without blocking Qt."""
        loop = self._loop
        if loop is None:
            self._shutdown_requested = True
            return

        def shutdown() -> None:
            self._shutdown_requested = True
            if self._active_task is not None and not self._active_task.done():
                self._active_task.cancel()

            if self._commands is not None:
                self._commands.put_nowait(("shutdown", None))

        loop.call_soon_threadsafe(shutdown)
