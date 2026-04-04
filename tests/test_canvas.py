from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.canvas import ImageCanvas
from astroview.core.contracts import ZoomState
from astroview.core.source_catalog import SourceCatalog, SourceRecord


class TestImageCanvas(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _image(width: int, height: int) -> QImage:
        image = QImage(width, height, QImage.Format.Format_Grayscale8)
        image.fill(0)
        return image

    def test_restore_view_state_preserves_relative_view_when_image_size_changes(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.resize(400, 300)
            canvas.show()
            self._app.processEvents()

            canvas.set_image(self._image(100, 100))
            canvas.resetTransform()
            canvas.scale(2.0, 2.0)
            canvas.set_zoom_state(ZoomState(scale_factor=2.0, mode="custom"))
            canvas.centerOn(25, 75)
            self._app.processEvents()

            state = canvas.capture_view_state()
            canvas.set_image(self._image(200, 200))
            canvas.restore_view_state(state)
            self._app.processEvents()

            center = canvas.mapToScene(canvas.viewport().rect().center())
            expected_x = state["center_x"] * 200.0
            expected_y = state["center_y"] * 200.0
            self.assertAlmostEqual(canvas.transform().m11(), 1.0, places=2)
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, 1.0, places=2)
            self.assertEqual(canvas.zoom_state.mode, "custom")
            self.assertAlmostEqual(center.x(), expected_x, delta=3.0)
            self.assertAlmostEqual(center.y(), expected_y, delta=3.0)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_restore_view_state_keeps_same_scale_for_same_size_image(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.resize(400, 300)
            canvas.show()
            self._app.processEvents()

            canvas.set_image(self._image(120, 120))
            canvas.resetTransform()
            canvas.scale(1.6, 1.6)
            canvas.set_zoom_state(ZoomState(scale_factor=1.6, mode="custom"))
            canvas.centerOn(90, 30)
            self._app.processEvents()

            state = canvas.capture_view_state()
            canvas.set_image(self._image(120, 120))
            canvas.restore_view_state(state)
            self._app.processEvents()

            center = canvas.mapToScene(canvas.viewport().rect().center())
            expected_x = state["center_x"] * 120.0
            expected_y = state["center_y"] * 120.0
            self.assertAlmostEqual(canvas.transform().m11(), 1.6, places=2)
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, 1.6, places=2)
            self.assertAlmostEqual(center.x(), expected_x, delta=1.0)
            self.assertAlmostEqual(center.y(), expected_y, delta=1.0)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_double_clicking_source_overlay_emits_source_index(self) -> None:
        canvas = ImageCanvas()
        captured_indices: list[int] = []
        try:
            canvas.resize(300, 300)
            canvas.show()
            canvas.set_image(self._image(100, 100))
            canvas.draw_sources(SourceCatalog(records=[
                SourceRecord(source_id=1, x=40.0, y=55.0, a=4.0, b=3.0),
            ]))
            canvas.source_double_clicked.connect(captured_indices.append)
            self._app.processEvents()

            view_pos = canvas.mapFromScene(40.0, 55.0)
            QTest.mouseDClick(
                canvas.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(view_pos.x(), view_pos.y()),
            )
            self._app.processEvents()

            self.assertEqual(captured_indices, [0])
        finally:
            canvas.close()
            canvas.deleteLater()


if __name__ == "__main__":
    unittest.main()
