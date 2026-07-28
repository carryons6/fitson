from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.canvas import ImageCanvas
from astroview.app.contracts import ViewFeedbackState
from astroview.app.magnifier_overlay import MagnifierOverlay
from astroview.core.contracts import ZoomState
from astroview.core.source_catalog import SourceCatalog, SourceRecord


class _WheelEvent:
    def __init__(self, delta: int) -> None:
        self._delta = delta
        self.ignored = False

    def angleDelta(self) -> QPoint:
        return QPoint(0, self._delta)

    def ignore(self) -> None:
        self.ignored = True


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

    def test_fit_and_manual_zoom_report_actual_transform_scale(self) -> None:
        canvas = ImageCanvas()
        emitted_scales: list[float] = []
        try:
            canvas.resize(400, 300)
            canvas.show()
            canvas.set_image(self._image(1000, 800))
            canvas.zoom_changed.connect(emitted_scales.append)
            self._app.processEvents()

            canvas.fit_to_window()
            fitted_scale = canvas.transform().m11()
            self.assertNotAlmostEqual(fitted_scale, 1.0, places=2)
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, fitted_scale)
            self.assertEqual(canvas.zoom_state.mode, "fit")
            self.assertAlmostEqual(emitted_scales[-1], fitted_scale)

            canvas.zoom_in()
            zoomed_scale = canvas.transform().m11()
            self.assertAlmostEqual(
                zoomed_scale,
                min(fitted_scale * 1.15, canvas._MAX_ZOOM),
            )
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, zoomed_scale)
            self.assertEqual(canvas.zoom_state.mode, "custom")
            self.assertAlmostEqual(emitted_scales[-1], zoomed_scale)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_manual_zoom_is_bounded_between_minimum_and_maximum(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.set_image(self._image(100, 100))
            canvas.show_actual_pixels()

            for _ in range(100):
                canvas.zoom_in()
            self.assertAlmostEqual(canvas.transform().m11(), canvas._MAX_ZOOM)
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, canvas._MAX_ZOOM)

            for _ in range(200):
                canvas.zoom_out()
            self.assertAlmostEqual(canvas.transform().m11(), canvas._MIN_ZOOM)
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, canvas._MIN_ZOOM)

            canvas.wheelEvent(_WheelEvent(-120))
            self.assertAlmostEqual(canvas.transform().m11(), canvas._MIN_ZOOM)
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, canvas._MIN_ZOOM)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_zoom_commands_do_nothing_without_an_image(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.scale(2.0, 2.0)
            canvas.set_zoom_state(ZoomState(scale_factor=2.0, mode="custom"))
            initial_scale = canvas.transform().m11()
            wheel_event = _WheelEvent(120)

            canvas.fit_to_window()
            canvas.show_actual_pixels()
            canvas.zoom_in()
            canvas.zoom_out()
            canvas.wheelEvent(wheel_event)

            self.assertTrue(wheel_event.ignored)
            self.assertAlmostEqual(canvas.transform().m11(), initial_scale)
            self.assertAlmostEqual(canvas.zoom_state.scale_factor, initial_scale)
            self.assertEqual(canvas.zoom_state.mode, "custom")
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_left_click_emits_pixel_only_after_release(self) -> None:
        canvas = ImageCanvas()
        captured_positions: list[tuple[float, float]] = []
        try:
            canvas.resize(300, 300)
            canvas.show()
            canvas.set_image(self._image(100, 100))
            canvas.pixel_clicked.connect(
                lambda x, y: captured_positions.append((x, y))
            )
            self._app.processEvents()

            view_pos = canvas.mapFromScene(40.0, 55.0)
            QTest.mousePress(
                canvas.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                view_pos,
            )
            self._app.processEvents()
            self.assertEqual(captured_positions, [])

            QTest.mouseRelease(
                canvas.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                view_pos,
            )
            self._app.processEvents()
            self.assertEqual(len(captured_positions), 1)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_left_drag_does_not_emit_pixel_click(self) -> None:
        canvas = ImageCanvas()
        captured_positions: list[tuple[float, float]] = []
        try:
            canvas.resize(300, 300)
            canvas.show()
            canvas.set_image(self._image(1000, 1000))
            canvas.pixel_clicked.connect(
                lambda x, y: captured_positions.append((x, y))
            )
            self._app.processEvents()

            start = canvas.viewport().rect().center()
            end = start + QPoint(QApplication.startDragDistance() + 20, 0)
            QTest.mousePress(
                canvas.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                start,
            )
            QTest.mouseMove(canvas.viewport(), end)
            QTest.mouseRelease(
                canvas.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                end,
            )
            self._app.processEvents()

            self.assertEqual(captured_positions, [])
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_double_clicking_empty_canvas_requests_open(self) -> None:
        canvas = ImageCanvas()
        requests: list[bool] = []
        try:
            canvas.resize(300, 300)
            canvas.show()
            canvas.open_requested.connect(lambda: requests.append(True))
            self._app.processEvents()

            QTest.mouseDClick(
                canvas.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                canvas.viewport().rect().center(),
            )
            self._app.processEvents()

            self.assertEqual(requests, [True])
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_double_clicking_source_overlay_emits_source_index(self) -> None:
        canvas = ImageCanvas()
        captured_indices: list[int] = []
        open_requests: list[bool] = []
        try:
            canvas.resize(300, 300)
            canvas.show()
            canvas.set_image(self._image(100, 100))
            canvas.draw_sources(SourceCatalog(records=[
                SourceRecord(source_id=1, x=40.0, y=55.0, a=4.0, b=3.0),
            ]))
            canvas.source_double_clicked.connect(captured_indices.append)
            canvas.open_requested.connect(lambda: open_requests.append(True))
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
            self.assertEqual(open_requests, [])
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_feedback_state_renders_title_and_detail_text(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.resize(400, 300)
            canvas.show()
            canvas.set_feedback_state(
                ViewFeedbackState(
                    status="empty",
                    title="No Image Loaded",
                    detail="Drop FITS files here or press Ctrl+O.",
                    visible=True,
                )
            )
            self._app.processEvents()

            text = canvas._feedback_item.toPlainText()
            self.assertIn("No Image Loaded", text)
            self.assertIn("Drop FITS files here", text)
            self.assertTrue(canvas._feedback_background_item.isVisible())
            self.assertGreater(canvas._feedback_background_item.brush().color().alpha(), 0)
            self.assertGreater(canvas._feedback_item.defaultTextColor().lightness(), 180)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_loading_feedback_uses_high_contrast_text(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.resize(400, 300)
            canvas.show()
            canvas.set_feedback_state(
                ViewFeedbackState(
                    status="loading",
                    title="Rendering Preview",
                    detail="Preparing the first visible render for this frame.",
                    visible=True,
                )
            )
            self._app.processEvents()

            self.assertTrue(canvas._feedback_background_item.isVisible())
            self.assertGreater(canvas._feedback_item.defaultTextColor().lightness(), 180)
            self.assertGreater(canvas._feedback_background_item.brush().color().alpha(), 0)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_set_magnifier_visible_switches_to_custom_cursor(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.set_magnifier_visible(True)
            self.assertNotEqual(canvas.viewport().cursor().shape(), Qt.CursorShape.ArrowCursor)

            canvas.set_magnifier_visible(False)
            self.assertEqual(canvas.viewport().cursor().shape(), Qt.CursorShape.ArrowCursor)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_magnifier_overlay_formats_coordinates_with_two_decimals(self) -> None:
        overlay = MagnifierOverlay()
        try:
            overlay._scene_x = 123.456
            overlay._scene_y = 78.9
            self.assertEqual(overlay.coordinate_text(), "(123.46, 78.90)")
        finally:
            overlay.deleteLater()

    def test_scene_pos_from_view_pos_preserves_fractional_precision(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.resetTransform()
            canvas.scale(2.0, 2.0)
            inverse, invertible = canvas.viewportTransform().inverted()
            self.assertTrue(invertible)
            scene_pos = canvas._scene_pos_from_view_pos(QPointF(11.5, 7.25))
            expected = inverse.map(QPointF(11.5, 7.25))
            self.assertAlmostEqual(scene_pos.x(), expected.x(), places=2)
            self.assertAlmostEqual(scene_pos.y(), expected.y(), places=2)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_scene_pos_from_integer_view_pos_uses_pixel_center(self) -> None:
        canvas = ImageCanvas()
        try:
            canvas.resetTransform()
            inverse, invertible = canvas.viewportTransform().inverted()
            self.assertTrue(invertible)
            scene_pos = canvas._scene_pos_from_view_pos(QPoint(11, 7))
            expected = inverse.map(QPointF(11.5, 7.5))
            self.assertAlmostEqual(scene_pos.x(), expected.x(), places=2)
            self.assertAlmostEqual(scene_pos.y(), expected.y(), places=2)
        finally:
            canvas.close()
            canvas.deleteLater()


if __name__ == "__main__":
    unittest.main()
