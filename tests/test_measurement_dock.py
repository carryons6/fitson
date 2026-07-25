from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.i18n import install_translator
from astroview.app.measurement_dock import MeasurementDock
from astroview.core.contracts import ROISelection
from astroview.core.measurement_service import ApertureMeasurement, ROIStatistics


class TestMeasurementDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        install_translator(self._app, "en")

    def test_image_shape_enables_bounded_center_controls_and_emits_parameters(self) -> None:
        dock = MeasurementDock()
        requests: list[tuple[float, float, float, float, float]] = []
        dock.aperture_measurement_requested.connect(
            lambda *values: requests.append(tuple(float(value) for value in values))
        )
        try:
            self.assertFalse(dock.measure_button.isEnabled())
            dock.set_image_shape(100, 80)
            self.assertTrue(dock.measure_button.isEnabled())
            self.assertEqual(dock.center_x_spin.maximum(), 99.0)
            self.assertEqual(dock.center_y_spin.maximum(), 79.0)

            dock.set_center(12.5, 23.5)
            dock.aperture_radius_spin.setValue(4.0)
            dock.background_inner_radius_spin.setValue(7.0)
            dock.background_outer_radius_spin.setValue(10.0)
            dock.measure_button.click()

            self.assertEqual(requests, [(12.5, 23.5, 4.0, 7.0, 10.0)])
            self.assertEqual(
                dock.aperture_parameters(),
                {
                    "center_x": 12.5,
                    "center_y": 23.5,
                    "aperture_radius": 4.0,
                    "background_inner_radius": 7.0,
                    "background_outer_radius": 10.0,
                },
            )
        finally:
            dock.deleteLater()

    def test_roi_and_aperture_results_are_rendered_without_non_finite_text(self) -> None:
        dock = MeasurementDock()
        roi_result = ROIStatistics(
            roi=ROISelection(x0=3, y0=4, width=5, height=6),
            pixel_count=30,
            finite_pixel_count=28,
            invalid_pixel_count=2,
            minimum=1.0,
            maximum=9.0,
            mean=4.5,
            median=4.0,
            standard_deviation=2.0,
            sum_value=float("inf"),
        )
        aperture_result = ApertureMeasurement(
            center_x=10.0,
            center_y=11.0,
            aperture_radius=4.0,
            background_inner_radius=7.0,
            background_outer_radius=10.0,
            aperture_pixel_count=49,
            aperture_finite_pixel_count=48,
            background_pixel_count=160,
            background_finite_pixel_count=159,
            invalid_pixel_count=2,
            aperture_sum=1234.0,
            background_per_pixel=10.0,
            background_rms=2.0,
            background_total=480.0,
            net_flux=754.0,
            flux_uncertainty=15.0,
            snr=50.266666,
            centroid_x=10.25,
            centroid_y=10.75,
            fwhm=3.2,
            peak_above_background=float("nan"),
        )
        try:
            dock.set_roi_statistics(roi_result)
            dock.set_aperture_measurement(aperture_result)

            self.assertEqual(dock.roi_value_labels["region"].text(), "x=3, y=4, 5 × 6")
            self.assertEqual(dock.roi_value_labels["finite_invalid"].text(), "28 / 2")
            self.assertEqual(dock.roi_value_labels["sum"].text(), "—")
            self.assertEqual(dock.aperture_value_labels["net_flux"].text(), "754")
            self.assertEqual(dock.aperture_value_labels["centroid"].text(), "10.25, 10.75")
            self.assertEqual(dock.aperture_value_labels["peak"].text(), "—")
            self.assertNotIn("nan", dock.aperture_value_labels["peak"].text().lower())
            self.assertNotIn("inf", dock.roi_value_labels["sum"].text().lower())
        finally:
            dock.deleteLater()

    def test_busy_error_clear_and_no_image_states_are_non_modal(self) -> None:
        dock = MeasurementDock()
        clear_events: list[bool] = []
        dock.clear_requested.connect(lambda: clear_events.append(True))
        try:
            dock.set_image_shape(20, 10)
            dock.set_busy(True)
            self.assertFalse(dock.measure_button.isEnabled())
            self.assertEqual(dock.status_label.text(), "Measuring...")

            dock.set_error("bad annulus")
            self.assertTrue(dock.measure_button.isEnabled())
            self.assertIn("bad annulus", dock.status_label.text())

            dock.roi_value_labels["sum"].setText("42")
            dock.clear_button.click()
            self.assertEqual(clear_events, [True])
            self.assertEqual(dock.roi_value_labels["sum"].text(), "—")
            self.assertEqual(dock.status_label.text(), "Measurement results cleared.")

            dock.set_image_shape(None, None)
            self.assertFalse(dock.measure_button.isEnabled())
            self.assertEqual(dock.status_label.text(), "Load an image to begin measuring.")

            dock.set_busy(True)
            dock.set_image_shape(None, None)
            dock.set_image_shape(20, 10)
            self.assertTrue(dock.measure_button.isEnabled())
        finally:
            dock.deleteLater()

    def test_aperture_result_completes_busy_state(self) -> None:
        dock = MeasurementDock()
        result = ApertureMeasurement(
            center_x=5.0,
            center_y=5.0,
            aperture_radius=2.0,
            background_inner_radius=3.0,
            background_outer_radius=4.0,
            aperture_pixel_count=13,
            aperture_finite_pixel_count=13,
            background_pixel_count=24,
            background_finite_pixel_count=24,
            invalid_pixel_count=0,
            aperture_sum=130.0,
            background_per_pixel=10.0,
            background_rms=1.0,
            background_total=130.0,
            net_flux=0.0,
            flux_uncertainty=4.5,
            snr=0.0,
            centroid_x=None,
            centroid_y=None,
            fwhm=None,
            peak_above_background=0.0,
        )
        try:
            dock.set_image_shape(11, 11)
            dock.set_busy(True)
            self.assertFalse(dock.measure_button.isEnabled())

            dock.set_aperture_measurement(result)

            self.assertTrue(dock.measure_button.isEnabled())
            self.assertEqual(dock.status_label.text(), "Aperture measurement updated.")
        finally:
            dock.deleteLater()

    def test_measurement_ui_uses_chinese_translator(self) -> None:
        install_translator(self._app, "zh_CN")
        dock = MeasurementDock()
        try:
            self.assertEqual(dock.windowTitle(), "测量工作台")
            self.assertEqual(dock.measure_button.text(), "测量孔径")
            self.assertEqual(dock.status_label.text(), "请加载图像后开始测量。")
            dock.set_image_shape(12, 8)
            self.assertEqual(dock.status_label.text(), "就绪 — 图像为 12 × 8 像素。")
        finally:
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
