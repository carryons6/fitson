from __future__ import annotations

import gc
import os
import time
import unittest
from unittest.mock import Mock
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from astroview.app.sep_controller import SEPController
from astroview.core.contracts import ROISelection
from astroview.core.fits_data import FITSData
from astroview.core.sep_service import SEPParameters


class _Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in self.callbacks:
            callback(*args)


class _Thread:
    def __init__(self, parent=None) -> None:
        self.started, self.finished = _Signal(), _Signal()
        self.running = False
        self.interrupted = False
        self.waits = []

    def start(self) -> None:
        self.running = True
        self.started.emit()

    def isRunning(self) -> bool:
        return self.running

    def requestInterruption(self) -> None:
        self.interrupted = True

    def quit(self, *_args) -> None:
        pass

    def wait(self, milliseconds: int) -> bool:
        self.waits.append(milliseconds)
        return not self.running

    def deleteLater(self) -> None:
        pass

    def finish(self) -> None:
        self.running = False
        self.finished.emit()


def _worker(**options):
    worker = Mock()
    worker.options = options
    worker.extraction_ready = _Signal()
    worker.estimation_ready = _Signal()
    worker.extraction_error = _Signal()
    worker.finished = _Signal()
    return worker


class _Emitter(QObject):
    extraction_ready = Signal(int, object, object)
    estimation_ready = Signal(int, object, int)
    extraction_error = Signal(int, str)
    finished = Signal(int)

    def __init__(self, **options) -> None:
        super().__init__()
        self.options = options

    def cancel(self) -> None:
        pass

    @Slot()
    def run(self) -> None:
        self.extraction_ready.emit(self.options["request_id"], self.options["roi"], "catalog")
        self.finished.emit(self.options["request_id"])


class TestSEPController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _controller(self) -> tuple[SEPController, FITSData]:
        controller = SEPController(
            estimate_min_pixels=25, join_wait_ms=123,
            thread_factory=_Thread, worker_factory=_worker,
        )
        data = FITSData(data=np.zeros((10, 10)))
        controller.sync_context(0, data, data)
        return controller, data

    def _start(self, controller, data, *, full=False):
        roi = ROISelection(0, 0, 10, 10)
        self.assertTrue(controller.start(data, roi, SEPParameters(), full=full))
        return controller.task.thread, controller.task.worker, roi

    def test_small_roi_skips_estimation_and_clips_without_copying_input(self) -> None:
        controller, data = self._controller()
        params = SEPParameters(thresh=4)
        self.assertTrue(controller.start(data, ROISelection(-1, -1, 3, 3), params))
        options = controller.task.worker.options
        self.assertEqual(options["roi"], ROISelection(0, 0, 2, 2))
        self.assertFalse(options["estimate_only"])
        self.assertTrue(np.shares_memory(options["data_subarray"], data.data))
        params.thresh = 99
        self.assertEqual(options["params"].thresh, 4)
        controller.task.thread.finish()

    def test_low_estimate_waits_for_thread_exit_before_full_run(self) -> None:
        controller, data = self._controller()
        thread, worker, roi = self._start(controller, data)
        full_runs = []
        controller.full_run_requested.connect(full_runs.append)
        worker.estimation_ready.emit(1, roi, 0)
        worker.finished.emit(1)
        self.assertEqual(full_runs, [])
        self.assertIs(controller.task.thread, thread)
        self.assertIsNotNone(controller.pending_launch)
        thread.finish()
        self.assertEqual(full_runs, [roi])
        self.assertFalse(controller.is_running)

    def test_confirmation_before_or_after_thread_exit_launches_once(self) -> None:
        for confirm_before_exit in (True, False):
            with self.subTest(confirm_before_exit=confirm_before_exit):
                controller, data = self._controller()
                thread, worker, roi = self._start(controller, data)
                prompts, full_runs = [], []
                controller.confirmation_requested.connect(prompts.append)
                controller.full_run_requested.connect(full_runs.append)
                worker.estimation_ready.emit(1, roi, 100)
                self.assertEqual(len(prompts), 1)
                self.assertTrue(prompts[0].dense)
                self.assertEqual(prompts[0].expected, 2500)
                if confirm_before_exit:
                    self.assertTrue(controller.confirm())
                    self.assertEqual(full_runs, [])
                    thread.finish()
                else:
                    thread.finish()
                    self.assertEqual(full_runs, [])
                    self.assertTrue(controller.confirm())
                self.assertEqual(full_runs, [roi])
                self.assertFalse(controller.confirm())

    def test_declining_confirmation_discards_the_chained_run(self) -> None:
        controller, data = self._controller()
        thread, worker, roi = self._start(controller, data)
        full_runs = []
        controller.full_run_requested.connect(full_runs.append)
        worker.estimation_ready.emit(1, roi, 100)
        self.assertTrue(controller.decline_confirmation())
        thread.finish()
        self.assertEqual(full_runs, [])
        self.assertIsNone(controller.confirm_pending)

    def test_cancellation_rejects_all_queued_events_and_keeps_timed_out_slot(self) -> None:
        controller, data = self._controller()
        thread, worker, roi = self._start(controller, data)
        received = []
        controller.full_run_requested.connect(received.append)
        controller.confirmation_requested.connect(received.append)
        controller.error_accepted.connect(received.append)
        controller.extraction_accepted.connect(lambda *args: received.append(args))
        controller.pending_launch = controller.pending_action(roi)
        self.assertFalse(controller.cancel(wait=True))
        worker.estimation_ready.emit(1, roi, 100)
        worker.extraction_ready.emit(1, roi, "late catalog")
        worker.extraction_error.emit(1, "late error")
        self.assertEqual(received, [])
        self.assertIs(controller.task.thread, thread)
        self.assertEqual(thread.waits, [123])
        worker.cancel.assert_called_once_with()
        thread.finish()
        self.assertEqual(received, [])
        self.assertFalse(controller.is_running)

    def test_replacing_data_at_same_frame_index_invalidates_results_and_confirmation(self) -> None:
        controller, data = self._controller()
        thread, worker, roi = self._start(controller, data)
        received = []
        controller.extraction_accepted.connect(lambda *args: received.append(args))
        controller.full_run_requested.connect(received.append)
        worker.estimation_ready.emit(1, roi, 100)
        replacement = FITSData(data=np.ones((10, 10)))
        controller.sync_context(0, replacement, replacement)
        worker.extraction_ready.emit(1, roi, "stale")
        self.assertFalse(controller.confirm())
        thread.finish()
        self.assertEqual(received, [])

    def test_active_data_must_match_session_frame(self) -> None:
        controller, data = self._controller()
        thread, worker, roi = self._start(controller, data, full=True)
        accepted = []
        controller.extraction_accepted.connect(lambda *args: accepted.append(args))
        controller.sync_context(0, data, FITSData(data=np.zeros((10, 10))))
        worker.extraction_ready.emit(1, roi, "wrong context")
        self.assertEqual(accepted, [])
        thread.finish()

    def test_old_cleanup_and_worker_cannot_mutate_next_full_run(self) -> None:
        controller, data = self._controller()
        old_thread, old_worker, roi = self._start(controller, data)
        controller.full_run_requested.connect(lambda selected: controller.start(data, selected, SEPParameters(), full=True))
        old_worker.estimation_ready.emit(1, roi, 0)
        old_thread.finish()
        thread, worker = controller.task.thread, controller.task.worker
        self.assertEqual(controller.task.active_request_id, 2)
        self.assertFalse(worker.options["estimate_only"])
        accepted = []
        controller.extraction_accepted.connect(lambda *args: accepted.append(args))
        controller.handle_thread_finished(1, old_thread, old_worker)
        old_worker.extraction_ready.emit(1, roi, "stale catalog")
        worker.extraction_ready.emit(2, roi, "new catalog")
        self.assertEqual(accepted, [(roi, "new catalog")])
        self.assertIs(controller.task.thread, thread)
        thread.finish()

    def test_closing_prevents_pending_full_run(self) -> None:
        controller, data = self._controller()
        thread, worker, roi = self._start(controller, data)
        full_runs = []
        controller.full_run_requested.connect(full_runs.append)
        worker.estimation_ready.emit(1, roi, 0)
        controller.closing = True
        controller.cancel()
        thread.finish()
        self.assertEqual(full_runs, [])
        self.assertFalse(controller.start(data, roi, SEPParameters()))

    def test_validation_rejects_empty_roi_missing_data_and_occupied_slot(self) -> None:
        controller, data = self._controller()
        reasons = []
        controller.validation_failed.connect(reasons.append)
        self.assertFalse(controller.start(None, ROISelection(0, 0, 1, 1), SEPParameters()))
        self.assertFalse(controller.start(data, ROISelection(20, 20, 1, 1), SEPParameters()))
        thread, worker, roi = self._start(controller, data)
        self.assertFalse(controller.start(data, roi, SEPParameters()))
        self.assertEqual(reasons, ["no_data", "empty_roi", "busy"])
        thread.finish()

    def test_context_does_not_keep_large_frame_arrays_alive(self) -> None:
        controller, data = self._controller()
        array = weakref.ref(data.data)
        del data
        gc.collect()
        self.assertIsNone(array())

    def test_real_worker_callbacks_are_applied_on_gui_thread(self) -> None:
        controller = SEPController(worker_factory=_Emitter)
        data = FITSData(data=np.zeros((2, 2)))
        controller.sync_context(0, data, data)
        results, threads, retired = [], [], []
        controller.extraction_accepted.connect(
            lambda roi, catalog: (results.append(catalog), threads.append(QThread.currentThread()))
        )
        controller.idle.connect(lambda: retired.append(True))
        controller.start(data, ROISelection(0, 0, 2, 2), SEPParameters())
        try:
            deadline = time.monotonic() + 3
            while not retired and time.monotonic() < deadline:
                self._app.processEvents()
                time.sleep(0.001)
            self.assertEqual(results, ["catalog"])
            self.assertEqual(threads, [self._app.thread()])
            self.assertEqual(retired, [True])
        finally:
            controller.closing = True
            controller.cancel(wait=True)
            controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
