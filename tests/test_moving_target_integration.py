from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.main_window import MainWindow
from astroview.core.contracts import ROISelection
from astroview.core.fits_data import FITSData
from astroview.core.moving_targets import (
    MovingTargetParameters,
    MovingTargetResult,
    MovingTargetTrack,
)


def _result() -> MovingTargetResult:
    track = MovingTargetTrack(
        target_id=1,
        hit_frames=(0, 1, 2, 3, 4),
        x0=10.0,
        y0=20.0,
        vx=2.0,
        vy=0.0,
        rms=0.1,
        median_snr=3.0,
        positions=np.array([[10.0 + 2.0 * i, 20.0] for i in range(5)]),
        measured_mask=np.ones(5, dtype=bool),
    )
    return MovingTargetResult(
        tracks=(track,),
        frame_count=5,
        roi=ROISelection(0, 0, 80, 60),
        seconds=np.arange(5, dtype=float),
        time_source="test",
        registration_shifts=np.zeros((5, 2)),
        registration_matches=(20,) * 5,
        registration_rms=(0.1,) * 5,
        source_counts=(25,) * 5,
        candidate_counts=(1,) * 5,
        static_source_count=20,
    )


class TestMovingTargetMainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _window(self) -> MainWindow:
        window = MainWindow()
        window.initialize(apply_startup_request=False)
        frames = [FITSData(path=f"f-{i}.fits", data=np.zeros((60, 80))) for i in range(5)]
        window._frames = frames
        window._frame_images = [QImage(80, 60, QImage.Format.Format_Grayscale8) for _ in frames]
        window._frame_dirty = [False] * 5
        window._frame_bkg_cache = [None] * 5
        window._frame_residual_cache = [None] * 5
        window._frame_cached_preview_dim = [0] * 5
        window.fits_service.current_data = frames[0]
        window._current_frame_index = 0
        window._sync_moving_target_context()
        return window

    def test_one_shot_roi_capture_does_not_run_single_frame_sep(self) -> None:
        window = self._window()
        try:
            window._moving_roi_capture_pending = True
            with patch.object(window, "_measure_roi") as measure, patch.object(window, "_start_sep_extract") as sep:
                window.handle_roi_selected(10, 12, 20, 18)
            self.assertEqual(window._moving_target_roi, ROISelection(10, 12, 20, 18))
            self.assertFalse(window._moving_roi_capture_pending)
            self.assertIsNotNone(window.canvas._moving_target_roi_item)
            self.assertIsNone(window.canvas._measurement_roi_item)
            measure.assert_not_called()
            sep.assert_not_called()

            with patch.object(window, "_measure_roi") as measure, patch.object(window, "_start_sep_extract") as sep:
                window.handle_roi_selected(2, 3, 10, 11)
            measure.assert_called_once()
            sep.assert_called_once()
        finally:
            window.close()
            window.deleteLater()

    def test_full_frame_clears_only_the_moving_target_roi_layer(self) -> None:
        window = self._window()
        try:
            measurement = ROISelection(2, 3, 10, 11)
            moving = ROISelection(10, 12, 20, 18)
            window.canvas.set_measurement_roi(measurement)
            window._moving_target_roi = moving
            window._sync_moving_target_context()
            self.assertIsNotNone(window.canvas._measurement_roi_item)
            self.assertIsNotNone(window.canvas._moving_target_roi_item)

            window._use_full_frame_for_moving_targets()

            self.assertIsNone(window._moving_target_roi)
            self.assertIsNone(window.canvas._moving_target_roi_item)
            self.assertIsNotNone(window.canvas._measurement_roi_item)
        finally:
            window.close()
            window.deleteLater()

    def test_starting_detection_consumes_pending_roi_capture(self) -> None:
        window = self._window()
        try:
            window._moving_roi_capture_pending = True
            with patch("astroview.app.main_window.QThread.start", autospec=True) as start:
                window._start_moving_target_detection(
                    MovingTargetParameters(),
                    1.0,
                    False,
                )
            self.assertFalse(window._moving_roi_capture_pending)
            start.assert_called_once()
        finally:
            window.close()
            window.deleteLater()

    def test_busy_moving_detection_status_is_not_overwritten_as_empty_roi(self) -> None:
        window = self._window()
        running_thread = Mock()
        running_thread.isRunning.return_value = True
        window._moving_target_thread = running_thread
        try:
            window.app_status_bar.showMessage = Mock()
            window.handle_roi_selected(10, 12, 20, 18)
            window.app_status_bar.showMessage.assert_called_once_with(
                window.tr("Wait for moving-target detection to finish before running SEP."),
                3000,
            )
        finally:
            window._moving_target_thread = None
            window.close()
            window.deleteLater()

    def test_display_roi_roundtrip_for_all_orientations(self) -> None:
        window = self._window()
        original = ROISelection(10, 12, 20, 18)
        orientations = (
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (True, True, False),
            (False, False, True),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        )
        try:
            for orientation in orientations:
                with self.subTest(orientation=orientation):
                    window._orientation = orientation
                    first = window._orient_edge_point(original.x0, original.y0, 80, 60)
                    second = window._orient_edge_point(
                        original.x0 + original.width,
                        original.y0 + original.height,
                        80,
                        60,
                    )
                    x0, x1 = sorted((int(round(first[0])), int(round(second[0]))))
                    y0, y1 = sorted((int(round(first[1])), int(round(second[1]))))
                    restored = window._display_roi_to_original(x0, y0, x1 - x0, y1 - y0)
                    self.assertEqual(restored, original)
        finally:
            window.close()
            window.deleteLater()

    def test_result_overlay_follows_current_frame_and_hides_in_comparison(self) -> None:
        window = self._window()
        try:
            window._moving_target_result = _result()
            window._redraw_moving_target_overlays()
            self.assertEqual(window.canvas._moving_target_centers, [(10.0, 20.0)])
            window._current_frame_index = 3
            window.fits_service.current_data = window._frames[3]
            window._redraw_moving_target_overlays()
            self.assertEqual(window.canvas._moving_target_centers, [(16.0, 20.0)])
            window._comparison_active = True
            window._redraw_moving_target_overlays()
            self.assertEqual(window.canvas._moving_target_centers, [])
        finally:
            window._comparison_active = False
            window.close()
            window.deleteLater()

    def test_stale_result_is_rejected_by_context_and_dataset_identity(self) -> None:
        window = self._window()
        worker = Mock()
        window._moving_target_worker = worker
        window._active_moving_target_request_id = 4
        window._moving_target_results_enabled = True
        signature = window._moving_target_dataset_signature()
        try:
            window._handle_moving_target_result_for_request(4, 99, signature, worker, _result())
            self.assertIsNone(window._moving_target_result)
            window._handle_moving_target_result_for_request(
                4,
                window._moving_target_context_generation,
                signature[:-1],
                worker,
                _result(),
            )
            self.assertIsNone(window._moving_target_result)
        finally:
            window._moving_target_worker = None
            window._active_moving_target_request_id = None
            window._moving_target_results_enabled = False
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
