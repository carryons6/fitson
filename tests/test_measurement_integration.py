from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from astroview.app.main_window import MainWindow
from astroview.core.contracts import ROISelection
from astroview.core.fits_data import FITSData


class TestMeasurementIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _window_with_image(self, data: np.ndarray) -> MainWindow:
        window = MainWindow()
        window.initialize(apply_startup_request=False)
        window._roi_action = "measure"
        frame = FITSData(path="measurement.fits", data=data)
        window._frames = [frame]
        window._frame_images = [QImage(data.shape[1], data.shape[0], QImage.Format.Format_Grayscale8)]
        window._frame_dirty = [False]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._frame_cached_preview_dim = [0]
        window.fits_service.current_data = frame
        window.measurement_dock.set_image_shape(data.shape[1], data.shape[0])
        return window

    def test_roi_statistics_populate_dock_and_overlay(self) -> None:
        window = self._window_with_image(np.arange(400, dtype=float).reshape(20, 20))
        try:
            window._measure_roi(ROISelection(2, 3, 5, 4))

            self.assertEqual(window._last_measurement_roi, ROISelection(2, 3, 5, 4))
            self.assertEqual(window.measurement_dock.roi_value_labels["pixels"].text(), "20")
            self.assertIsNotNone(window.canvas._measurement_roi_item)
        finally:
            window.close()
            window.deleteLater()

    def test_aperture_measurement_draws_source_and_annulus(self) -> None:
        yy, xx = np.mgrid[:41, :41]
        image = 10.0 + 100.0 * np.exp(-((xx - 20.0) ** 2 + (yy - 20.0) ** 2) / (2.0 * 2.0**2))
        window = self._window_with_image(image)
        try:
            window._measure_aperture(20.0, 20.0, 5.0, 8.0, 12.0)

            self.assertIsNotNone(window._last_aperture_measurement)
            self.assertEqual(len(window.canvas._aperture_items), 3)
            self.assertNotEqual(window.measurement_dock.aperture_value_labels["net_flux"].text(), "—")
            self.assertNotEqual(window.measurement_dock.aperture_value_labels["snr"].text(), "—")
        finally:
            window.close()
            window.deleteLater()

    def test_canvas_click_updates_center_in_original_orientation(self) -> None:
        window = self._window_with_image(np.zeros((10, 20), dtype=float))
        try:
            window._orientation = (True, False, False)
            window._handle_canvas_pixel_clicked(4.0, 3.0)
            self.assertEqual(window.measurement_dock.center_x_spin.value(), 15.0)
            self.assertEqual(window.measurement_dock.center_y_spin.value(), 3.0)

            window._roi_action = "extract"
            window._handle_canvas_pixel_clicked(8.0, 7.0)
            self.assertEqual(window.measurement_dock.center_x_spin.value(), 15.0)
            self.assertEqual(window.measurement_dock.center_y_spin.value(), 3.0)
        finally:
            window.close()
            window.deleteLater()

    def test_clear_removes_results_and_overlays(self) -> None:
        window = self._window_with_image(np.ones((20, 20), dtype=float))
        try:
            window._measure_roi(ROISelection(1, 1, 4, 4))
            window._clear_measurements()
            self.assertIsNone(window._last_measurement_roi)
            self.assertIsNone(window.canvas._measurement_roi_item)
            self.assertEqual(window.canvas._aperture_items, [])
            self.assertEqual(window.measurement_dock.roi_value_labels["pixels"].text(), "—")
        finally:
            window.close()
            window.deleteLater()

    def test_all_d4_orientations_preserve_half_open_roi_pixels(self) -> None:
        window = self._window_with_image(np.zeros((10, 20), dtype=float))
        original = ROISelection(3, 2, 5, 4)
        try:
            for _label, orientation in window._ORIENTATIONS:
                with self.subTest(orientation=orientation):
                    window._orientation = orientation
                    first = window._orient_edge_point(
                        original.x0,
                        original.y0,
                        20,
                        10,
                    )
                    second = window._orient_edge_point(
                        original.x0 + original.width,
                        original.y0 + original.height,
                        20,
                        10,
                    )
                    display_x0, display_x1 = sorted((int(first[0]), int(second[0])))
                    display_y0, display_y1 = sorted((int(first[1]), int(second[1])))
                    with patch.object(window, "_measure_roi") as measure:
                        with patch.object(window, "_start_sep_extract") as extract:
                            window._roi_action = "measure"
                            window.handle_roi_selected(
                                display_x0,
                                display_y0,
                                display_x1 - display_x0,
                                display_y1 - display_y0,
                            )
                    measure.assert_called_once_with(original)
                    extract.assert_not_called()

                    with patch.object(window, "_measure_roi") as measure:
                        with patch.object(window, "_start_sep_extract") as extract:
                            window._roi_action = "extract"
                            window.handle_roi_selected(
                                display_x0,
                                display_y0,
                                display_x1 - display_x0,
                                display_y1 - display_y0,
                            )
                    measure.assert_not_called()
                    extract.assert_called_once_with(original)

                    window._last_measurement_roi = original
                    window._redraw_measurement_overlays()
                    rect = window.canvas._measurement_roi_item.rect()
                    self.assertEqual(
                        (rect.x(), rect.y(), rect.width(), rect.height()),
                        (
                            float(display_x0),
                            float(display_y0),
                            float(display_x1 - display_x0),
                            float(display_y1 - display_y0),
                        ),
                    )
        finally:
            window.close()
            window.deleteLater()

    def test_parameter_change_and_failed_remeasure_invalidate_old_aperture(self) -> None:
        image = np.ones((41, 41), dtype=float)
        image[20, 20] = 100.0
        window = self._window_with_image(image)
        try:
            window._measure_aperture(20.0, 20.0, 4.0, 7.0, 10.0)
            self.assertIsNotNone(window._last_aperture_measurement)

            window.measurement_dock.center_x_spin.setValue(21.0)
            self.assertIsNone(window._last_aperture_measurement)
            self.assertEqual(window.canvas._aperture_items, [])
            self.assertEqual(window.measurement_dock.aperture_value_labels["net_flux"].text(), "—")

            window._measure_aperture(20.0, 20.0, 10.0, 8.0, 12.0)
            self.assertIsNone(window._last_aperture_measurement)
            self.assertIn("failed", window.measurement_dock.status_label.text().lower())
        finally:
            window.close()
            window.deleteLater()

    def test_comparison_display_blocks_click_and_photometry(self) -> None:
        window = self._window_with_image(np.ones((30, 30), dtype=float))
        try:
            window.measurement_dock.set_center(5.0, 6.0)
            window._comparison_active = True
            window._handle_canvas_pixel_clicked(10.0, 11.0)
            window._measure_aperture(10.0, 11.0, 3.0, 5.0, 8.0)
            self.assertEqual(window.measurement_dock.center_x_spin.value(), 5.0)
            self.assertEqual(window.measurement_dock.center_y_spin.value(), 6.0)
            self.assertIsNone(window._last_aperture_measurement)
        finally:
            window._comparison_active = False
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
