from __future__ import annotations

import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from astroview.app.comparison_worker import ComparisonDisplayResult, ComparisonWorker
from astroview.app.main_window import MainWindow
from astroview.core.fits_data import FITSData
from astroview.core.image_comparison import ComparisonMode, compare_fits_images


class TestComparisonWorker(unittest.TestCase):
    def test_worker_renders_shared_scale_side_by_side_inputs(self) -> None:
        worker = ComparisonWorker(
            FITSData(data=np.arange(16, dtype=float).reshape(4, 4)),
            FITSData(data=np.arange(16, dtype=float).reshape(4, 4) + 10.0),
            mode="side_by_side",
            alignment="pixel",
            stretch_name="Linear",
            interval_name="MinMax",
            manual_limits=None,
        )
        results: list[ComparisonDisplayResult] = []
        worker.result_ready.connect(results.append)

        worker.run()

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].result.success)
        self.assertEqual(results[0].left_u8.shape, (4, 4))
        self.assertEqual(results[0].right_u8.shape, (4, 4))
        self.assertLess(int(results[0].left_u8.max()), int(results[0].right_u8.max()))

    def test_worker_renders_difference_and_returns_core_failures(self) -> None:
        difference_worker = ComparisonWorker(
            FITSData(data=np.full((3, 3), 5.0)),
            FITSData(data=np.full((3, 3), 2.0)),
            mode="difference",
            alignment="pixel",
            stretch_name="Linear",
            interval_name="MinMax",
            manual_limits=None,
        )
        difference_results: list[ComparisonDisplayResult] = []
        difference_worker.result_ready.connect(difference_results.append)
        difference_worker.run()
        self.assertTrue(difference_results[0].result.success)
        self.assertEqual(difference_results[0].difference_u8.shape, (3, 3))

        failure_worker = ComparisonWorker(
            FITSData(data=np.zeros((2, 2))),
            FITSData(data=np.zeros((3, 3))),
            mode="side_by_side",
            alignment="pixel",
            stretch_name="Linear",
            interval_name="MinMax",
            manual_limits=None,
        )
        failure_results: list[ComparisonDisplayResult] = []
        failure_worker.result_ready.connect(failure_results.append)
        failure_worker.run()
        self.assertFalse(failure_results[0].result.success)
        self.assertIsNone(failure_results[0].left_u8)


class TestComparisonMainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _window(self) -> MainWindow:
        window = MainWindow()
        window.initialize(apply_startup_request=False)
        left = FITSData(path="left.fits", data=np.arange(12, dtype=float).reshape(3, 4))
        right = FITSData(path="right.fits", data=np.arange(12, dtype=float).reshape(3, 4) + 2.0)
        window._frames = [left, right]
        window._frame_images = [
            QImage(4, 3, QImage.Format.Format_Grayscale8),
            QImage(4, 3, QImage.Format.Format_Grayscale8),
        ]
        window._frame_dirty = [False, False]
        window._frame_bkg_cache = [None, None]
        window._frame_residual_cache = [None, None]
        window._frame_cached_preview_dim = [0, 0]
        window.fits_service.current_data = left
        window._comparison_left_index = 0
        window._comparison_right_index = 1
        window._sync_comparison_inputs()
        return window

    def test_side_by_side_result_uses_one_synchronized_canvas(self) -> None:
        window = self._window()
        worker = Mock()
        window._comparison_worker = worker
        window._active_comparison_request_id = 9
        window._comparison_results_enabled = True
        core_result = compare_fits_images(
            window._frames[0],
            window._frames[1],
            mode="side_by_side",
            alignment="pixel",
        )
        display = ComparisonDisplayResult(
            result=core_result,
            left_u8=np.zeros((3, 4), dtype=np.uint8),
            right_u8=np.full((3, 4), 255, dtype=np.uint8),
        )
        try:
            window._handle_comparison_result_for_request(9, 0, 1, worker, display)
            self.assertTrue(window._comparison_active)
            self.assertEqual(window.canvas.current_image.width(), 10)
            self.assertEqual(window.canvas.current_image.height(), 3)
            self.assertFalse(window.canvas.compass.isVisible())
        finally:
            window._comparison_worker = None
            window._active_comparison_request_id = None
            window._comparison_results_enabled = False
            window.close()
            window.deleteLater()

    def test_blink_phase_and_clear_restore_current_frame(self) -> None:
        window = self._window()
        worker = Mock()
        window._comparison_worker = worker
        window._active_comparison_request_id = 3
        window._comparison_results_enabled = True
        result = compare_fits_images(
            window._frames[0],
            window._frames[1],
            mode=ComparisonMode.BLINK,
            alignment="pixel",
        )
        display = ComparisonDisplayResult(
            result=result,
            left_u8=np.zeros((3, 4), dtype=np.uint8),
            right_u8=np.full((3, 4), 255, dtype=np.uint8),
        )
        try:
            window._handle_comparison_result_for_request(3, 0, 1, worker, display)
            window._show_comparison_blink_phase(1)
            self.assertEqual(window.canvas.current_image.pixelColor(0, 0).red(), 255)
            window._clear_comparison()
            self.assertFalse(window._comparison_active)
            self.assertIsNone(window._comparison_left_index)
            self.assertEqual(window.canvas.current_image.width(), 4)
        finally:
            window._comparison_worker = None
            window._active_comparison_request_id = None
            window._comparison_results_enabled = False
            window.close()
            window.deleteLater()

    def test_cancel_rejects_a_queued_comparison_result(self) -> None:
        window = self._window()
        worker = Mock()
        thread = Mock()
        thread.isRunning.return_value = True
        window._comparison_worker = worker
        window._comparison_thread = thread
        window._active_comparison_request_id = 12
        window._comparison_results_enabled = True
        result = compare_fits_images(window._frames[0], window._frames[1])
        display = ComparisonDisplayResult(
            result=result,
            left_u8=np.zeros((3, 4), dtype=np.uint8),
            right_u8=np.zeros((3, 4), dtype=np.uint8),
        )
        try:
            self.assertFalse(window._stop_comparison_worker(wait=False))
            window._handle_comparison_result_for_request(12, 0, 1, worker, display)
            self.assertFalse(window._comparison_active)
            worker.cancel.assert_called_once_with()
        finally:
            window._comparison_worker = None
            window._comparison_thread = None
            window._active_comparison_request_id = None
            window._comparison_results_enabled = False
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
