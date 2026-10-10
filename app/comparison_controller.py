"""Image-comparison requests and lifecycle, independent of presentation."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.fits_data import FITSData
from .comparison_worker import ComparisonDisplayResult, ComparisonWorker
from .task_lifecycle import TaskLifecycle


class ComparisonSignalRelay(QObject):
    """Deliver comparison results and retirement on the controller's thread."""

    def __init__(
        self,
        controller: ComparisonController,
        request_id: int,
        left_index: int,
        right_index: int,
        thread: QThread,
        worker: ComparisonWorker,
    ) -> None:
        super().__init__(controller)
        self._controller = controller
        self._request_id = request_id
        self._left_index = left_index
        self._right_index = right_index
        self._thread = thread
        self._worker = worker

    @Slot(object)
    def handle_result(self, display: ComparisonDisplayResult) -> None:
        self._controller.handle_result(
            self._request_id, self._left_index, self._right_index, self._worker, display
        )

    @Slot(str)
    def handle_error(self, detail: str) -> None:
        self._controller.handle_error(self._request_id, self._worker, detail)

    @Slot()
    def handle_thread_finished(self) -> None:
        self._controller.handle_thread_finished(self._request_id, self._thread, self._worker)


class ComparisonController(QObject):
    """Own the selected pair and one worker; callers own dialogs and display."""

    comparison_started = Signal()
    result_accepted = Signal(object)
    error_accepted = Signal(str)
    comparison_finished = Signal()

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
        self.left_index: int | None = None
        self.right_index: int | None = None
        self.closing = False
        self._join_wait_ms = max(0, int(join_wait_ms))
        self._thread_factory = thread_factory or QThread
        self._worker_factory = worker_factory or ComparisonWorker

    def start(self, left: FITSData, right: FITSData, **worker_options: Any) -> bool:
        if self.closing or self.left_index is None or self.right_index is None or self.task.running:
            return False
        # A finished thread can still be waiting for GUI cleanup. Retire it
        # before reserving the slot; its later callback cannot retire this job.
        if self.task.thread is not None:
            self.handle_thread_finished(self.task.active_request_id, self.task.thread, self.task.worker)
        if self.task.thread is not None:
            return False
        thread = self._thread_factory(self)
        worker = self._worker_factory(left, right, **worker_options)
        request_id = self.task.activate(thread, worker)
        relay = ComparisonSignalRelay(
            self, request_id, self.left_index, self.right_index, thread, worker
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result_ready.connect(relay.handle_result)
        worker.comparison_error.connect(relay.handle_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.handle_thread_finished)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.comparison_started.emit()
        thread.start()
        return True

    def handle_result(
        self,
        request_id: int,
        left_index: int,
        right_index: int,
        worker: Any,
        display: ComparisonDisplayResult,
    ) -> None:
        if (
            not self.closing
            and self.task.accepts(request_id, worker)
            and (left_index, right_index) == (self.left_index, self.right_index)
        ):
            self.result_accepted.emit(display)

    def handle_error(self, request_id: int, worker: Any, detail: str) -> None:
        if not self.closing and self.task.accepts(request_id, worker):
            self.error_accepted.emit(detail)

    def handle_thread_finished(self, request_id: int | None, thread: Any, worker: Any) -> None:
        if self.task.retire(request_id, thread, worker):
            self.comparison_finished.emit()

    def stop(self, *, wait: bool = False) -> bool:
        thread, worker = self.task.thread, self.task.worker
        request_id = self.task.active_request_id
        self.task.results_enabled = False
        if worker is not None:
            worker.cancel()
        stopped = self.task.request_stop(wait_ms=self._join_wait_ms if wait else None)
        if stopped and thread is not None:
            self.handle_thread_finished(request_id, thread, worker)
        return stopped
