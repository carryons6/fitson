"""SEP estimate, confirmation, extraction, and worker ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.contracts import ROISelection
from ..core.fits_data import FITSData
from ..core.sep_service import SEPParameters
from .sep_extract_worker import SEPExtractWorker
from .task_lifecycle import TaskLifecycle


@dataclass(frozen=True, slots=True)
class PendingSEPAction:
    roi: ROISelection
    frame_index: int
    context_generation: int
    frame_identity: int | None


@dataclass(frozen=True, slots=True)
class SEPCountEstimate:
    count: int
    sigma: float
    user_sigma: float
    density: float
    expected: int
    dense: bool


class _SEPSignalRelay(QObject):
    """Keep all state transitions on the controller's GUI thread."""

    def __init__(self, controller: SEPController, request_id: int, thread: Any, worker: Any) -> None:
        super().__init__(controller)
        self._controller = controller
        self._request_id = request_id
        self._thread = thread
        self._worker = worker

    @Slot(int, object, object)
    def handle_result(self, request_id: int, roi: ROISelection, catalog: Any) -> None:
        self._controller.handle_result(request_id, roi, catalog, worker=self._worker)

    @Slot(int, object, int)
    def handle_estimate(self, request_id: int, roi: ROISelection, count: int) -> None:
        self._controller.handle_estimate(request_id, roi, count, worker=self._worker)

    @Slot(int, str)
    def handle_error(self, request_id: int, detail: str) -> None:
        self._controller.handle_error(request_id, detail, worker=self._worker)

    @Slot()
    def handle_thread_finished(self) -> None:
        self._controller.handle_thread_finished(self._request_id, self._thread, self._worker)


class SEPController(QObject):
    """Own estimate-to-extract transitions without retaining session arrays.

    The composition root supplies frame identity and starts each requested full
    run with current data/parameters. Only integer identities are retained here;
    the worker alone owns its input slice during computation.
    """

    validation_failed = Signal(str)
    run_started = Signal(object, bool)
    confirmation_requested = Signal(object)
    full_run_requested = Signal(object)
    extraction_accepted = Signal(object, object)
    error_accepted = Signal(str)
    idle = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        join_wait_ms: int = 6_000,
        estimate_min_pixels: int = 1_000_000,
        estimate_sigma: float = 15.0,
        dense_field_per_mpx: float = 150,
        large_count_warning: int = 5_000,
        thread_factory: Callable[..., Any] | None = None,
        worker_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.task = TaskLifecycle()
        self.closing = False
        self.context_generation = 0
        self.frame_index = 0
        self.frame_identity: int | None = None
        self.context_valid = False
        self.active_context_generation: int | None = None
        self.active_frame_index: int | None = None
        self.active_frame_identity: int | None = None
        self.is_estimate_phase = False
        self.pending_extract_roi: ROISelection | None = None
        self.pending_launch: PendingSEPAction | None = None
        self.confirm_pending: PendingSEPAction | None = None
        self.parameters = SEPParameters()
        self._join_wait_ms = max(0, int(join_wait_ms))
        self._estimate_min_pixels = estimate_min_pixels
        self._estimate_sigma = estimate_sigma
        self._dense_field_per_mpx = dense_field_per_mpx
        self._large_count_warning = large_count_warning
        self._thread_factory = thread_factory or QThread
        self._worker_factory = worker_factory or SEPExtractWorker

    @property
    def is_running(self) -> bool:
        return self.task.active_request_id is not None or self.task.thread is not None

    def sync_context(self, frame_index: int, frame_data: Any, active_data: Any) -> None:
        self.frame_index = frame_index
        self.frame_identity = id(frame_data) if frame_data is not None else None
        self.context_valid = frame_data is not None and frame_data is active_data

    def pending_action(self, roi: ROISelection) -> PendingSEPAction:
        return PendingSEPAction(roi, self.frame_index, self.context_generation, self.frame_identity)

    def action_is_current(self, action: PendingSEPAction) -> bool:
        return bool(
            not self.closing and self.context_valid
            and action.frame_index == self.frame_index
            and action.context_generation == self.context_generation
            and action.frame_identity == self.frame_identity
        )

    def request_is_current(self, request_id: int, worker: Any = None) -> bool:
        return bool(
            not self.closing and self.context_valid
            and self.task.accepts(request_id, self.task.worker if worker is None else worker)
            and self.active_frame_index == self.frame_index
            and self.active_context_generation == self.context_generation
            and self.active_frame_identity == self.frame_identity
        )

    def clear_pending(self) -> None:
        self.pending_extract_roi = None
        self.pending_launch = None
        self.confirm_pending = None

    def set_parameters(self, params: SEPParameters) -> None:
        self.parameters = replace(params)

    def start(self, data: FITSData | None, roi: ROISelection, params: SEPParameters, *, full: bool = False) -> bool:
        if self.closing:
            return False
        if self.is_running:
            self.validation_failed.emit("busy")
            return False
        if data is None or data.data is None:
            self.validation_failed.emit("no_data")
            return False
        height, width = data.data.shape[:2]
        x0, y0 = max(0, min(roi.x0, width)), max(0, min(roi.y0, height))
        x1 = max(x0, min(roi.x0 + roi.width, width))
        y1 = max(y0, min(roi.y0 + roi.height, height))
        if x1 <= x0 or y1 <= y0:
            self.validation_failed.emit("empty_roi")
            return False
        normalized = ROISelection(x0, y0, x1 - x0, y1 - y0)
        estimate = not full and normalized.width * normalized.height >= self._estimate_min_pixels
        self.clear_pending()
        self.pending_extract_roi = normalized if estimate else None
        self.set_parameters(params)
        thread = self._thread_factory(self)
        worker = self._worker_factory(
            request_id=self.task.request_id + 1,
            data_subarray=data.data[y0:y1, x0:x1],
            roi=normalized,
            params=self.parameters,
            wcs=data.wcs if data.has_wcs else None,
            estimate_only=estimate,
            estimate_threshold=self._estimate_sigma if estimate else None,
        )
        request_id = self.task.activate(thread, worker)
        self.active_context_generation = self.context_generation
        self.active_frame_index = self.frame_index
        self.active_frame_identity = self.frame_identity
        self.is_estimate_phase = estimate
        relay = _SEPSignalRelay(self, request_id, thread, worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.extraction_ready.connect(relay.handle_result)
        worker.estimation_ready.connect(relay.handle_estimate)
        worker.extraction_error.connect(relay.handle_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.handle_thread_finished)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.run_started.emit(normalized, estimate)
        thread.start()
        return True

    def handle_estimate(self, request_id: int, roi: ROISelection, count: int, *, worker: Any = None) -> None:
        if not self.request_is_current(request_id, worker):
            return
        pending_roi, self.pending_extract_roi = self.pending_extract_roi, None
        if pending_roi is None:
            return
        user_sigma = max(float(self.parameters.thresh), 0.1)
        area_mpx = max(pending_roi.width * pending_roi.height / 1_000_000.0, 1e-6)
        density = count / area_mpx
        expected = int(round(count * (self._estimate_sigma / user_sigma) ** 2))
        dense = density >= self._dense_field_per_mpx
        action = self.pending_action(pending_roi)
        if not dense and expected < self._large_count_warning:
            self.pending_launch = action
            return
        self.confirm_pending = action
        self.confirmation_requested.emit(
            SEPCountEstimate(count, self._estimate_sigma, user_sigma, density, expected, dense)
        )

    def confirm(self) -> bool:
        pending, self.confirm_pending = self.confirm_pending, None
        if pending is None or not self.action_is_current(pending):
            return False
        if self.task.thread is not None:
            self.pending_launch = pending
        else:
            self.full_run_requested.emit(pending.roi)
        return True

    def decline_confirmation(self) -> bool:
        had_confirmation = self.confirm_pending is not None
        self.clear_pending()
        return had_confirmation

    def handle_result(self, request_id: int, roi: ROISelection, catalog: Any, *, worker: Any = None) -> None:
        if self.request_is_current(request_id, worker):
            self.extraction_accepted.emit(roi, catalog)

    def handle_error(self, request_id: int, detail: str, *, worker: Any = None) -> None:
        if self.request_is_current(request_id, worker):
            self.clear_pending()
            self.error_accepted.emit(detail)

    def handle_thread_finished(self, request_id: int | None, thread: Any, worker: Any) -> None:
        if not self.task.retire(request_id, thread, worker):
            return
        self.active_context_generation = None
        self.active_frame_index = None
        self.active_frame_identity = None
        pending, self.pending_launch = self.pending_launch, None
        if pending is not None and self.action_is_current(pending):
            self.full_run_requested.emit(pending.roi)
        else:
            self.idle.emit()

    def cancel(self, *, wait: bool = False) -> bool:
        self.context_generation += 1
        self.clear_pending()
        thread, worker = self.task.thread, self.task.worker
        request_id = self.task.active_request_id
        self.task.results_enabled = False
        if self.task.running and worker is not None:
            try:
                worker.cancel()
            except Exception:
                pass
        stopped = self.task.request_stop(wait_ms=self._join_wait_ms if wait else None)
        if stopped and thread is not None:
            self.handle_thread_finished(request_id, thread, worker)
        elif thread is None:
            self.task.active_request_id = None
            self.active_context_generation = None
            self.active_frame_index = None
            self.active_frame_identity = None
        return stopped
