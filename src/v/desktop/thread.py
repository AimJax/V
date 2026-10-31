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

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._commands: asyncio.Queue | None = None
        self._active_task: asyncio.Task | None = None
        self._shutdown_requested = False

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
