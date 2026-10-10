"""Bounded FITS loading and stale-result filtering, independent of widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .file_load_worker import FITSLoadWorker
from .task_lifecycle import TaskLifecycle


@dataclass(frozen=True, slots=True)
class FrameLoadRequest:
    paths: tuple[str, ...]
    hdu_index: int | None = None
    append: bool = False


class LoadSignalRelay(QObject):
    """Receive worker signals on the controller's GUI thread."""

    def __init__(
        self,
        controller: FileLoadController,
        request_id: int,
        thread: QThread,
        worker: FITSLoadWorker,
    ) -> None:
        super().__init__(controller)
        self._controller = controller
        self._request_id = request_id
        self._thread = thread
        self._worker = worker

    @Slot(object, object)
    def handle_loaded(self, data: Any, preview: Any) -> None:
        self._controller.handle_loaded(self._request_id, self._worker, data, preview)

    @Slot(str, str)
    def handle_error(self, path: str, detail: str) -> None:
        self._controller.handle_error(self._request_id, self._worker, path, detail)

    @Slot(int, int, str)
    def handle_progress(self, completed: int, total: int, path: str) -> None:
        self._controller.handle_progress(self._request_id, self._worker, completed, total, path)

    @Slot()
    def handle_finished(self) -> None:
        self._controller.handle_finished(self._request_id, self._worker)

    @Slot()
    def handle_thread_finished(self) -> None:
        self._controller.handle_thread_finished(self._request_id, self._thread, self._worker)


class FileLoadController(QObject):
    """Own one loader, replacing pending intent while cancellation winds down.

    ``launch_requested`` lets the composition root prepare the session and
    snapshot render preferences before calling ``launch``. The controller owns
    thread creation and cleanup; frame acceptance and presentation stay outside.
    """

    launch_requested = Signal(object)
    request_queued = Signal(object)
    frame_accepted = Signal(object, object)
    error_accepted = Signal(str, str)
    progress_accepted = Signal(int, int, str)
    load_finished = Signal()
    load_cancelled = Signal()
    idle = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        join_wait_ms: int = 6_000,
        thread_factory: Callable[..., Any] | None = None,
        worker_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.task = TaskLifecycle()
        self.pending: FrameLoadRequest | None = None
        self.closing = False
        self.cancel_feedback_pending = False
        self.append_mode = False
        self.total_count = 0
        self.completed_count = 0
        self.error_count = 0
        self._join_wait_ms = max(0, int(join_wait_ms))
        self._thread_factory = thread_factory or QThread
        self._worker_factory = worker_factory or FITSLoadWorker

    def start(self, request: FrameLoadRequest) -> None:
        if not request.paths or self.closing:
            return
        if self.task.thread is not None:
            self.pending = request
            self.cancel_feedback_pending = False
            if self.task.running:
                self.stop()
                self.request_queued.emit(request)
            else:
                self.task.results_enabled = False
                self.handle_thread_finished(
                    self.task.active_request_id, self.task.thread, self.task.worker
                )
            return
        self.pending = None
        self.launch_requested.emit(request)

    def launch(self, request: FrameLoadRequest, **worker_options: Any) -> bool:
        if self.closing or self.task.thread is not None:
            return False
        thread = self._thread_factory(self)
        worker = self._worker_factory(
            list(request.paths), hdu_index=request.hdu_index, **worker_options
        )
        request_id = self.task.activate(thread, worker)
        relay = LoadSignalRelay(self, request_id, thread, worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.file_loaded.connect(relay.handle_loaded)
        worker.file_error.connect(relay.handle_error)
        worker.progress.connect(relay.handle_progress)
        worker.finished.connect(relay.handle_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.handle_thread_finished)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return True

    def stop(self, *, wait: bool = False) -> bool:
        thread, worker = self.task.thread, self.task.worker
        request_id = self.task.active_request_id
        stopped = self.task.request_stop(wait_ms=self._join_wait_ms if wait else None)
        if stopped and thread is not None:
            self.handle_thread_finished(request_id, thread, worker)
        return stopped

    def handle_thread_finished(self, request_id: int | None, thread: Any, worker: Any) -> None:
        if not self.task.retire(request_id, thread, worker):
            return
        pending, self.pending = self.pending, None
        if not self.closing and pending is not None:
            self.launch_requested.emit(pending)
            return
        if not self.closing and self.cancel_feedback_pending:
            self.cancel_feedback_pending = False
            self.load_cancelled.emit()
        self.idle.emit()

    def request_is_current(self, request_id: int, worker: Any) -> bool:
        return not self.closing and self.task.accepts(request_id, worker)

    def handle_loaded(self, request_id: int, worker: Any, data: Any, preview: Any) -> None:
        if self.request_is_current(request_id, worker):
            self.frame_accepted.emit(data, preview)

    def handle_error(self, request_id: int, worker: Any, path: str, detail: str) -> None:
        if self.request_is_current(request_id, worker):
            self.error_accepted.emit(path, detail)

    def handle_progress(
        self, request_id: int, worker: Any, completed: int, total: int, path: str
    ) -> None:
        if self.request_is_current(request_id, worker):
            self.progress_accepted.emit(completed, total, path)

    def handle_finished(self, request_id: int, worker: Any) -> None:
        if self.request_is_current(request_id, worker):
            self.load_finished.emit()
