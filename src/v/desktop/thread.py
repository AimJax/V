"""Qt thread hosting V's persistent asynchronous local runtime."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QThread, Signal

from v.desktop.service import DesktopService, DesktopSnapshot, DesktopTurnResult


class DesktopRuntimeThread(QThread):
    """Keep async model, memory, and SQLite work off the GUI thread."""

    ready = Signal(object)
    startup_failed = Signal(str)
    token_received = Signal(str)
    turn_completed = Signal(object)
    operation_failed = Signal(str)
    session_changed = Signal(object)
    memory_list_ready = Signal(object)
    memory_updated = Signal(object)
    memory_deleted = Signal(str)
    memory_backup_completed = Signal(str)
    memory_operation_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._commands: asyncio.Queue | None = None
        self._active_task: asyncio.Task | None = None
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
                break

            if command == "send":
                self._active_task = asyncio.create_task(
                    service.send_message(payload, self.token_received.emit)
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

            if command == "new":
                try:
                    self.session_changed.emit(service.new_conversation())
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

    def new_conversation(self) -> None:
        self._post("new")

    def select_conversation(self, conversation_id: str) -> None:
        self._post("select", conversation_id)

    def list_memories(
        self,
        query: str = "",
        memory_type: str = "",
        provenance: str = "",
    ) -> None:
        self._memory_filters = (query, memory_type, provenance)
        self._post("memory_list", self._memory_filters)

    def update_memory(self, memory_id: str, changes: dict) -> None:
        self._post("memory_update", (memory_id, changes))

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
