from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.comparison_dock import ComparisonDock
from astroview.app.i18n import install_translator
from astroview.core.image_comparison import (
    ComparisonAlignment,
    ComparisonFailureCode,
    ComparisonMode,
    ImageComparisonResult,
)


class TestComparisonDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        install_translator(self._app, "en")

    def test_frame_controls_and_compare_request_are_host_driven(self) -> None:
        dock = ComparisonDock()
        selected: list[int] = []
        requests: list[tuple[str, str]] = []
        dock.image_selection_requested.connect(selected.append)
        dock.comparison_requested.connect(
            lambda mode, alignment: requests.append((mode, alignment))
        )
        try:
            self.assertFalse(dock.compare_button.isEnabled())
            dock.select_left_button.click()
            dock.select_right_button.click()
            self.assertEqual(selected, [0, 1])

            dock.set_inputs("science <A>.fits [2]", "reference & B.fits [0]")
            self.assertEqual(
                dock.input_names(),
                ("science <A>.fits [2]", "reference & B.fits [0]"),
            )
            self.assertEqual(dock.left_label.textFormat(), Qt.TextFormat.PlainText)
            self.assertEqual(dock.status_label.textFormat(), Qt.TextFormat.PlainText)
            self.assertTrue(dock.compare_button.isEnabled())

            dock.set_mode(ComparisonMode.DIFFERENCE)
            dock.set_alignment(ComparisonAlignment.PIXEL)
            dock.compare_button.click()

            self.assertEqual(
                requests,
                [(ComparisonMode.DIFFERENCE.value, ComparisonAlignment.PIXEL.value)],
            )
            self.assertFalse(dock.blink_toggle_button.isEnabled())
        finally:
            dock.stop_blinking()
            dock.deleteLater()

    def test_blink_interval_and_phase_signals_have_bounded_state(self) -> None:
        dock = ComparisonDock()
        intervals: list[int] = []
        phases: list[int] = []
        active: list[bool] = []
        dock.blink_interval_changed.connect(intervals.append)
        dock.blink_phase_changed.connect(phases.append)
        dock.blink_active_changed.connect(active.append)
        try:
            dock.set_inputs("A", "B")
            dock.set_mode("blink")
            dock.set_blink_interval_ms(700)
            self.assertEqual(dock.blink_interval_ms(), 700)
            self.assertEqual(dock._blink_timer.interval(), 700)
            self.assertEqual(intervals, [700])
            with self.assertRaises(ValueError):
                dock.set_blink_interval_ms(99)
            with self.assertRaises(ValueError):
                dock.set_blink_interval_ms(True)
            with self.assertRaises(ValueError):
                dock.set_blink_interval_ms(700.0)

            dock.set_comparison_available(True)
            dock.blink_toggle_button.click()
            self.assertTrue(dock.is_blinking())
            self.assertEqual(phases, [0])
            self.assertEqual(active, [True])

            dock._advance_blink()
            self.assertEqual(phases, [0, 1])
            dock.stop_blinking()
            self.assertFalse(dock.is_blinking())
            self.assertEqual(active, [True, False])
        finally:
            dock.stop_blinking()
            dock.deleteLater()

    def test_view_sync_relays_to_opposite_pane_and_validates_values(self) -> None:
        dock = ComparisonDock()
        zoom: list[tuple[int, float, float, float]] = []
        pan: list[tuple[int, float, float]] = []
        enabled: list[bool] = []
        dock.zoom_sync_requested.connect(
            lambda target, scale, x, y: zoom.append((target, scale, x, y))
        )
        dock.pan_sync_requested.connect(
            lambda target, x, y: pan.append((target, x, y))
        )
        dock.view_sync_changed.connect(enabled.append)
        try:
            self.assertTrue(dock.view_sync_enabled())
            dock.relay_zoom_state(0, 2.0, 12.5, 8.0)
            dock.relay_pan_state(1, 3.0, 4.0)
            self.assertEqual(zoom, [(1, 2.0, 12.5, 8.0)])
            self.assertEqual(pan, [(0, 3.0, 4.0)])

            dock.set_view_sync_enabled(False)
            self.assertEqual(enabled, [False])
            dock.relay_pan_state(0, 9.0, 10.0)
            self.assertEqual(pan, [(0, 3.0, 4.0)])

            with self.assertRaises(ValueError):
                dock.relay_zoom_state(2, 1.0, 0.0, 0.0)
            with self.assertRaises(ValueError):
                dock.relay_zoom_state(0, float("nan"), 0.0, 0.0)
        finally:
            dock.stop_blinking()
            dock.deleteLater()

    def test_result_state_stops_blinking_and_surfaces_failure_reason(self) -> None:
        dock = ComparisonDock()
        try:
            dock.set_inputs("A", "B")
            dock.set_mode("blink")
            dock.set_comparison_result(
                ImageComparisonResult(success=True, mode=ComparisonMode.BLINK)
            )
            self.assertTrue(dock.blink_toggle_button.isEnabled())
            dock.blink_toggle_button.click()
            self.assertTrue(dock.is_blinking())

            dock.set_comparison_result(
                ImageComparisonResult.failure(
                    ComparisonFailureCode.SHAPE_MISMATCH,
                    "Frames have different shapes.",
                    mode=ComparisonMode.BLINK,
                )
            )
            self.assertFalse(dock.is_blinking())
            self.assertFalse(dock.blink_toggle_button.isEnabled())
            self.assertEqual(dock.status_label.text(), "Frames have different shapes.")
        finally:
            dock.stop_blinking()
            dock.deleteLater()

    def test_comparison_controls_use_chinese_translator(self) -> None:
        install_translator(self._app, "zh_CN")
        dock = ComparisonDock()
        try:
            self.assertEqual(dock.windowTitle(), "图像比较")
            self.assertEqual(dock.select_left_button.text(), "选择帧 A...")
            self.assertEqual(dock.compare_button.text(), "比较")
            self.assertEqual(dock.status_label.text(), "请选择两幅要比较的图像。")
            dock.set_inputs("A", "B")
            self.assertEqual(dock.status_label.text(), "已准备好进行比较。")
        finally:
            dock.stop_blinking()
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
