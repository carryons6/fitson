from __future__ import annotations

import itertools
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QImage, QTransform
from PySide6.QtWidgets import QApplication, QWidget

from astroview.app.canvas import ImageCanvas
from astroview.app.magnifier_overlay import MagnifierOverlay
from astroview.core.contracts import ZoomState


def qimage(data: np.ndarray) -> QImage:
    array = np.ascontiguousarray(data, dtype=np.uint8)
    return QImage(array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format.Format_Grayscale8).copy()


def oriented(array, orientation):
    horizontal, vertical, transpose = orientation
    result = array.T if transpose else array
    if horizontal:
        result = result[:, ::-1]
    if vertical:
        result = result[::-1, :]
    return result


class TestSampledCanvas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_odd_size_sampled_export_matches_repeat_crop_then_orient(self):
        canvas = ImageCanvas()
        try:
            texture = np.arange(12, dtype=np.uint8).reshape(3, 4) * 20
            expanded = np.repeat(np.repeat(texture, 2, axis=0), 2, axis=1)[:5, :7]
            for orientation in itertools.product((False, True), repeat=3):
                with self.subTest(orientation=orientation):
                    expected = oriented(expanded, orientation)
                    image = qimage(oriented(texture, orientation))
                    height, width = expected.shape
                    offset = (
                        width - image.width() * 2 if orientation[0] else 0,
                        height - image.height() * 2 if orientation[1] else 0,
                    )
                    canvas.set_image(image, logical_size=(width, height), sample_step=2, sampling_offset=offset)
                    exported = canvas.render_scene_image()
                    self.assertEqual((exported.width(), exported.height()), (width, height))
                    actual = [[exported.pixelColor(x, y).red() for x in range(width)] for y in range(height)]
                    np.testing.assert_array_equal(actual, expected)
                    # Raw export uses the same crop while excluding overlays.
                    canvas.set_markers([(2, 2)], radius=3)
                    raw = canvas.render_raster_image()
                    raw_pixels = [[raw.pixelColor(x, y).red() for x in range(width)] for y in range(height)]
                    np.testing.assert_array_equal(raw_pixels, expected)
                    canvas.clear_markers()
                    self.assertEqual(canvas._pixmap_item.pixmap().width(), image.width())
                    self.assertEqual(canvas.capture_view_state()['image_width'], width)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_final_raster_preserves_preview_zoom_and_original_coordinate_center(self):
        canvas = ImageCanvas()
        try:
            canvas.resize(400, 300)
            canvas.show()
            canvas.set_image(qimage(np.zeros((251, 401))), logical_size=(801, 501), sample_step=2)
            canvas.scale(1.5, 1.5)
            canvas.set_zoom_state(ZoomState(scale_factor=1.5, mode='custom'))
            canvas.centerOn(511, 301)
            self.app.processEvents()
            state = canvas.capture_view_state()
            canvas.set_image(qimage(np.zeros((501, 801))))
            canvas.restore_view_state(state)
            self.app.processEvents()
            self.assertAlmostEqual(canvas.transform().m11(), 1.5)
            new_state = canvas.capture_view_state()
            self.assertAlmostEqual(new_state['center_x'], state['center_x'], delta=0.002)
            self.assertAlmostEqual(new_state['center_y'], state['center_y'], delta=0.002)
            canvas.show_actual_pixels()
            self.assertEqual(canvas.transform().m11(), 1.0)
            self.assertEqual(canvas._pixmap_item.image_to_scene.m11(), 1.0)
        finally:
            canvas.close()
            canvas.deleteLater()

    def test_magnifier_samples_logical_coordinates_and_clips_partial_edge_blocks(self):
        parent = QWidget()
        reference = MagnifierOverlay(parent)
        preview = MagnifierOverlay(parent)
        try:
            parent.resize(500, 500)
            # Odd logical dimensions crop half of the final sampled blocks.
            texture = np.arange(12, dtype=np.uint8).reshape(3, 4) * 20
            expanded = np.repeat(np.repeat(texture, 2, axis=0), 2, axis=1)[:5, :7]
            for orientation in itertools.product((False, True), repeat=3):
                with self.subTest(orientation=orientation):
                    full = qimage(oriented(expanded, orientation))
                    sampled = qimage(oriented(texture, orientation))
                    width, height = full.width(), full.height()
                    offset_x = width - sampled.width() * 2 if orientation[0] else 0
                    offset_y = height - sampled.height() * 2 if orientation[1] else 0
                    reference.update_position(full, 1.0, 1.0, QPoint(10, 10), 3.0)
                    preview.update_position(
                        sampled, 1.0, 1.0, QPoint(10, 10), 3.0,
                        image_to_scene=QTransform(2, 0, 0, 2, offset_x, offset_y),
                        logical_image_rect=QRectF(0, 0, width, height),
                    )
                    actual = preview.grab().toImage()
                    expected = reference.grab().toImage()
                    self.assertEqual(actual, expected)
                    self.assertEqual(preview.coordinate_text(), '(1.00, 1.00)')
        finally:
            parent.close()
            parent.deleteLater()


if __name__ == '__main__':
    unittest.main()
