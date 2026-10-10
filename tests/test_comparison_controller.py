from __future__ import annotations

import os
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from astroview.app.comparison_controller import ComparisonController
from astroview.core.fits_data import FITSData


class _Emitter(QObject):
    result_ready = Signal(object)
    comparison_error = Signal(str)
    finished = Signal()

    def cancel(self) -> None:
        pass

    @Slot()
    def run(self) -> None:
        self.result_ready.emit("comparison")
        self.finished.emit()


class TestComparisonController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _controller(self) -> ComparisonController:
        controller = ComparisonController(join_wait_ms=123)
        controller.left_index = 0
        controller.right_index = 1
        return controller

    def _options(self) -> dict:
        return dict(
            mode="blink", alignment="pixel", stretch_name="Linear",
            interval_name="ZScale", manual_limits=None,
        )

    def test_pair_and_worker_identity_reject_stale_results(self) -> None:
        controller = self._controller()
        thread, worker = Mock(), Mock()
        controller.task.activate(thread, worker)
        results = []
        controller.result_accepted.connect(results.append)
        controller.handle_result(0, 0, 1, worker, "old request")
        controller.handle_result(1, 0, 1, Mock(), "old worker")
        controller.handle_result(1, 1, 0, worker, "old selection")
        controller.handle_result(1, 0, 1, worker, "current")
        self.assertEqual(results, ["current"])

        controller.right_index = 2
        controller.handle_result(1, 0, 1, worker, "changed selection")
        self.assertEqual(results, ["current"])

    def test_cancel_rejects_result_and_error_without_freeing_running_slot(self) -> None:
        controller = self._controller()
        thread, worker = Mock(), Mock()
        thread.isRunning.return_value = True
        controller.task.activate(thread, worker)
        received = []
        controller.result_accepted.connect(received.append)
        controller.error_accepted.connect(received.append)
        self.assertFalse(controller.stop(wait=True))
        controller.handle_result(1, 0, 1, worker, "late result")
        controller.handle_error(1, worker, "late error")
        self.assertEqual(received, [])
        self.assertIs(controller.task.thread, thread)
        worker.cancel.assert_called_once_with()
        thread.wait.assert_called_once_with(123)
        self.assertFalse(controller.start(FITSData(), FITSData(), **self._options()))

    def test_retirement_of_old_request_cannot_clear_replacement(self) -> None:
        controller = self._controller()
        old_thread, old_worker = Mock(), Mock()
        old_thread.isRunning.return_value = False
        controller.task.activate(old_thread, old_worker)
        finished = []
        controller.comparison_finished.connect(lambda: finished.append(True))
        with patch("astroview.app.comparison_controller.QThread.start", autospec=True):
            self.assertTrue(controller.start(FITSData(), FITSData(), **self._options()))
        self.assertEqual(finished, [True])
        thread, worker = controller.task.thread, controller.task.worker
        self.assertEqual(controller.task.active_request_id, 2)
        controller.handle_thread_finished(1, old_thread, old_worker)
        self.assertIs(controller.task.thread, thread)
        self.assertIs(controller.task.worker, worker)
        self.assertEqual(finished, [True])
        controller.handle_thread_finished(2, thread, worker)
        self.assertEqual(finished, [True, True])
        controller.deleteLater()

    def test_closing_rejects_callbacks_and_new_work(self) -> None:
        controller = self._controller()
        thread, worker = Mock(), Mock()
        controller.task.activate(thread, worker)
        controller.closing = True
        received = []
        controller.result_accepted.connect(received.append)
        controller.error_accepted.connect(received.append)
        controller.handle_result(1, 0, 1, worker, "late result")
        controller.handle_error(1, worker, "late error")
        self.assertEqual(received, [])
        self.assertFalse(controller.start(FITSData(), FITSData(), **self._options()))

    def test_start_snapshots_inputs_and_render_options(self) -> None:
        controller = self._controller()
        left, right = FITSData(path="left.fits"), FITSData(path="right.fits")
        started = []
        controller.comparison_started.connect(lambda: started.append(True))
        with patch("astroview.app.comparison_controller.QThread.start", autospec=True):
            self.assertTrue(controller.start(left, right, **self._options()))
        worker, thread = controller.task.worker, controller.task.thread
        self.assertIs(worker.left, left)
        self.assertIs(worker.right, right)
        self.assertEqual(worker.mode, "blink")
        self.assertEqual(worker.interval_name, "ZScale")
        self.assertEqual(started, [True])
        controller.handle_thread_finished(1, thread, worker)
        controller.deleteLater()

    def test_real_worker_result_and_retirement_run_on_gui_thread(self) -> None:
        controller = ComparisonController(worker_factory=lambda *args, **kwargs: _Emitter())
        controller.left_index, controller.right_index = 0, 1
        results, threads, finished = [], [], []
        controller.result_accepted.connect(
            lambda result: (results.append(result), threads.append(QThread.currentThread()))
        )
        controller.comparison_finished.connect(lambda: finished.append(True))
        controller.start(FITSData(), FITSData())
        try:
            deadline = time.monotonic() + 3
            while not finished and time.monotonic() < deadline:
                self._app.processEvents()
                time.sleep(0.001)
            self.assertEqual(results, ["comparison"])
            self.assertEqual(threads, [self._app.thread()])
            self.assertEqual(finished, [True])
            self.assertIsNone(controller.task.thread)
        finally:
            controller.closing = True
            controller.stop(wait=True)
            controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
