from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.contracts import ROISelection
from ..core.moving_targets import MovingTargetParameters, MovingTargetResult
from .moving_target_worker import MovingTargetWorker


logger = logging.getLogger(__name__)


class _MovingTargetSignalRelay(QObject):
    """Attach one worker's immutable request identity to queued callbacks."""

    def __init__(
        self,
        controller: "MovingTargetController",
        request_id: int,
        context_generation: int,
        dataset_signature: tuple[int, ...],
        thread: QThread,
        worker: MovingTargetWorker,
    ) -> None:
        super().__init__(controller)
        self._controller = controller
        self._request_id = request_id
        self._context_generation = context_generation
        self._dataset_signature = dataset_signature
        self._thread = thread
        self._worker = worker

    @Slot(int, object)
    def handle_result(self, request_id: int, result: MovingTargetResult) -> None:
        self._controller.handle_result_for_request(
            request_id,
            self._context_generation,
            self._dataset_signature,
            self._worker,
            result,
        )

    @Slot(int, int, int, str)
    def handle_progress(self, request_id: int, completed: int, total: int, detail: str) -> None:
        self._controller.handle_progress_for_request(
            request_id,
            self._context_generation,
            self._dataset_signature,
            self._worker,
            completed,
            total,
            detail,
        )

    @Slot(int, str)
    def handle_error(self, request_id: int, detail: str) -> None:
        self._controller.handle_error_for_request(
            request_id,
            self._context_generation,
            self._dataset_signature,
            self._worker,
            detail,
        )

    @Slot()
    def handle_thread_finished(self) -> None:
        self._controller.clear_worker_refs(
            self._request_id,
            self._thread,
            self._worker,
        )


class MovingTargetController(QObject):
    """Own moving-target request state and its bounded worker lifecycle.

    The controller deliberately has no knowledge of ``MainWindow``, docks,
    canvases, dialogs, translation, or the application's global busy policy.
    Those presentation and cross-feature decisions remain at the composition
    root; this object owns only feature state and stale-result protection.
    """

    detection_started = Signal()
    result_cleared = Signal()
    result_accepted = Signal(object)
    progress_accepted = Signal(int, int, str)
    error_accepted = Signal(str)
    detection_finished = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        join_wait_ms: int = 6_000,
        thread_factory: Callable[[QObject], QThread] | None = None,
        worker_factory: Callable[..., MovingTargetWorker] | None = None,
    ) -> None:
        super().__init__(parent)
        self._join_wait_ms = max(0, int(join_wait_ms))
        self._thread_factory = thread_factory or QThread
        self._worker_factory = worker_factory or MovingTargetWorker

        self._dataset_signature: tuple[int, ...] = ()
        self._roi: ROISelection | None = None
        self._capture_pending = False
        self._result: MovingTargetResult | None = None
        self._thread: QThread | None = None
        self._worker: MovingTargetWorker | None = None
        self._request_id = 0
        self._active_request_id: int | None = None
        self._context_generation = 0
        self._results_enabled = False
        self._cancel_feedback_pending = False

    @property
    def roi(self) -> ROISelection | None:
        return self._roi

    @roi.setter
    def roi(self, value: ROISelection | None) -> None:
        self._roi = value

    @property
    def capture_pending(self) -> bool:
        return self._capture_pending

    @capture_pending.setter
    def capture_pending(self, value: bool) -> None:
        self._capture_pending = bool(value)

    @property
    def result(self) -> MovingTargetResult | None:
        return self._result

    @result.setter
    def result(self, value: MovingTargetResult | None) -> None:
        self._result = value

    @property
    def thread(self) -> QThread | None:
        return self._thread

    @thread.setter
    def thread(self, value: QThread | None) -> None:
        self._thread = value

    @property
    def worker(self) -> MovingTargetWorker | None:
        return self._worker

    @worker.setter
    def worker(self, value: MovingTargetWorker | None) -> None:
        self._worker = value

    @property
    def request_id(self) -> int:
        return self._request_id

    @request_id.setter
    def request_id(self, value: int) -> None:
        self._request_id = int(value)

    @property
    def active_request_id(self) -> int | None:
        return self._active_request_id

    @active_request_id.setter
    def active_request_id(self, value: int | None) -> None:
        self._active_request_id = None if value is None else int(value)

    @property
    def context_generation(self) -> int:
        return self._context_generation

    @context_generation.setter
    def context_generation(self, value: int) -> None:
        self._context_generation = int(value)

    @property
    def results_enabled(self) -> bool:
        return self._results_enabled

    @results_enabled.setter
    def results_enabled(self, value: bool) -> None:
        self._results_enabled = bool(value)

    @property
    def cancel_feedback_pending(self) -> bool:
        return self._cancel_feedback_pending

    @cancel_feedback_pending.setter
    def cancel_feedback_pending(self, value: bool) -> None:
        self._cancel_feedback_pending = bool(value)

    @property
    def is_running(self) -> bool:
        thread = self._thread
        if thread is None:
            return False
        try:
            return bool(thread.isRunning())
        except RuntimeError:
            return False

    def sync_sequence(self, frames: Iterable[Any]) -> None:
        """Refresh sequence identity without retaining large frame arrays."""

        self._dataset_signature = self.dataset_signature(frames)

    @staticmethod
    def dataset_signature(frames: Iterable[Any]) -> tuple[int, ...]:
        return tuple(id(frame) for frame in frames)

    def current_dataset_signature(self) -> tuple[int, ...]:
        return self._dataset_signature

    @staticmethod
    def common_frame_shape(frames: Iterable[Any]) -> tuple[int, int] | None:
        shape: tuple[int, int] | None = None
        for frame in frames:
            data = getattr(frame, "data", None)
            if data is None:
                return None
            array = np.asarray(data)
            if array.ndim != 2:
                return None
            current = (int(array.shape[1]), int(array.shape[0]))
            if shape is None:
                shape = current
            elif current != shape:
                return None
        return shape

    def begin_roi_capture(self) -> None:
        self._capture_pending = True

    def cancel_roi_capture(self) -> None:
        self._capture_pending = False

    def consume_captured_roi(self, roi: ROISelection) -> bool:
        """Apply *roi* only when a one-shot capture is pending."""

        if not self._capture_pending:
            return False
        self._capture_pending = False
        self._context_generation += 1
        self._roi = roi
        self.clear_result()
        return True

    def use_full_frame(self) -> None:
        self._capture_pending = False
        self._context_generation += 1
        self._roi = None
        self.clear_result()

    def clear_result(self) -> None:
        self._result = None
        self.result_cleared.emit()

    def start(
        self,
        *,
        frames: Iterable[Any],
        roi: ROISelection,
        parameters: MovingTargetParameters,
        fallback_cadence_seconds: float,
        prefer_header_times: bool,
    ) -> bool:
        """Launch one validated request, returning whether it was accepted."""

        if self.is_running:
            return False

        frame_snapshot = tuple(frames)
        self.sync_sequence(frame_snapshot)
        self._capture_pending = False
        self.clear_result()
        self._request_id += 1
        request_id = self._request_id
        context_generation = self._context_generation
        dataset_signature = self.current_dataset_signature()
        thread = self._thread_factory(self)
        worker = self._worker_factory(
            request_id=request_id,
            frames=list(frame_snapshot),
            roi=roi,
            parameters=parameters,
            fallback_cadence_seconds=fallback_cadence_seconds,
            prefer_header_times=prefer_header_times,
        )
        relay = _MovingTargetSignalRelay(
            self,
            request_id,
            context_generation,
            dataset_signature,
            thread,
            worker,
        )
        self._active_request_id = request_id
        self._results_enabled = True
        self._cancel_feedback_pending = False
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result_ready.connect(relay.handle_result)
        worker.progress.connect(relay.handle_progress)
        worker.detection_error.connect(relay.handle_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.handle_thread_finished)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.detection_started.emit()
        thread.start()
        return True

    def request_is_current(
        self,
        request_id: int,
        context_generation: int,
        dataset_signature: tuple[int, ...],
        worker: MovingTargetWorker,
    ) -> bool:
        return bool(
            self._results_enabled
            and request_id == self._active_request_id
            and context_generation == self._context_generation
            and dataset_signature == self.current_dataset_signature()
            and worker is self._worker
        )

    def handle_result_for_request(
        self,
        request_id: int,
        context_generation: int,
        dataset_signature: tuple[int, ...],
        worker: MovingTargetWorker,
        result: MovingTargetResult,
    ) -> None:
        if not self.request_is_current(
            request_id,
            context_generation,
            dataset_signature,
            worker,
        ):
            return
        self._result = result
        self.result_accepted.emit(result)

    def handle_progress_for_request(
        self,
        request_id: int,
        context_generation: int,
        dataset_signature: tuple[int, ...],
        worker: MovingTargetWorker,
        completed: int,
        total: int,
        detail: str,
    ) -> None:
        if not self.request_is_current(
            request_id,
            context_generation,
            dataset_signature,
            worker,
        ):
            return
        self.progress_accepted.emit(int(completed), int(total), str(detail))

    def handle_error_for_request(
        self,
        request_id: int,
        context_generation: int,
        dataset_signature: tuple[int, ...],
        worker: MovingTargetWorker,
        detail: str,
    ) -> None:
        if not self.request_is_current(
            request_id,
            context_generation,
            dataset_signature,
            worker,
        ):
            return
        self.error_accepted.emit(str(detail))

    def clear_worker_refs(
        self,
        request_id: int,
        thread: QThread,
        worker: MovingTargetWorker,
    ) -> None:
        if request_id != self._active_request_id:
            return
        if thread is not self._thread or worker is not self._worker:
            return
        cancelled = self._cancel_feedback_pending
        self._active_request_id = None
        self._results_enabled = False
        self._thread = None
        self._worker = None
        self._cancel_feedback_pending = False
        self.detection_finished.emit(cancelled)

    def stop(self, *, wait: bool = False) -> bool:
        """Cancel the active worker and optionally wait for bounded teardown."""

        thread = self._thread
        worker = self._worker
        request_id = self._active_request_id
        self._results_enabled = False
        if thread is None or worker is None or request_id is None:
            return True
        worker.cancel()
        try:
            running = thread.isRunning()
        except RuntimeError:
            running = False
        if running:
            thread.requestInterruption()
            thread.quit()
        if wait and running:
            thread.wait(self._join_wait_ms)
        try:
            running = thread.isRunning()
        except RuntimeError:
            running = False
        if not running:
            self.clear_worker_refs(request_id, thread, worker)
            return True
        return False

    def cancel(self, *, wait: bool = False) -> bool:
        self._cancel_feedback_pending = True
        return self.stop(wait=wait)

    def invalidate_sequence(self, *, clear_roi: bool) -> None:
        self._context_generation += 1
        self._dataset_signature = ()
        self._capture_pending = False
        self._cancel_feedback_pending = False
        self.stop(wait=False)
        if clear_roi:
            self._roi = None
        self.clear_result()


__all__ = ["MovingTargetController"]
