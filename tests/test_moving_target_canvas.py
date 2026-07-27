from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.canvas import ImageCanvas
from astroview.core.contracts import ROISelection


class TestMovingTargetCanvas(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_moving_target_layer_is_independent_and_transformable(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.set_image(QImage(80, 60, QImage.Format.Format_Grayscale8))
            canvas.set_markers([(5.0, 6.0)])
            canvas.set_moving_target_overlays(
                [{"label": "T1", "x": 10.0, "y": 12.0, "tooltip": "target"}],
                transform=lambda x, y: (x + 3.0, y + 4.0),
            )
            self.assertEqual(len(canvas._marker_items), 1)
            self.assertEqual(len(canvas._moving_target_items), 2)
            self.assertEqual(canvas._moving_target_centers, [(13.0, 16.0)])
            canvas.center_on_moving_target(0)
            canvas.clear_moving_target_overlays()
            self.assertEqual(len(canvas._moving_target_items), 0)
            self.assertEqual(len(canvas._marker_items), 1)

            canvas.set_moving_target_overlays(
                [
                    {"label": "bad", "x": float("nan"), "y": 1.0},
                    {"label": "T2", "x": 20.0, "y": 22.0},
                ]
            )
            self.assertEqual(canvas._moving_target_centers, [None, (20.0, 22.0)])
            canvas.center_on_moving_target(0)
        finally:
            canvas.deleteLater()

    def test_moving_target_roi_is_independent_from_measurement_roi(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.set_image(QImage(80, 60, QImage.Format.Format_Grayscale8))
            measurement = ROISelection(2, 3, 12, 10)
            moving = ROISelection(20, 15, 24, 18)
            canvas.set_measurement_roi(measurement)
            canvas.set_moving_target_roi(moving, transform=lambda x, y: (x + 1, y + 2))

            self.assertIsNotNone(canvas._measurement_roi_item)
            self.assertIsNotNone(canvas._moving_target_roi_item)
            rect = canvas._moving_target_roi_item.rect()
            self.assertEqual((rect.x(), rect.y(), rect.width(), rect.height()), (21.0, 17.0, 24.0, 18.0))

            canvas.clear_moving_target_roi()
            self.assertIsNone(canvas._moving_target_roi_item)
            self.assertIsNotNone(canvas._measurement_roi_item)
        finally:
            canvas.deleteLater()


if __name__ == "__main__":
    unittest.main()
