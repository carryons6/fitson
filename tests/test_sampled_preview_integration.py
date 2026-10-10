from __future__ import annotations

import itertools
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from astroview.app.main_window import MainWindow
from astroview.core.contracts import RenderResult, ResolvedRenderSpec, ZoomState
from astroview.core.fits_data import FITSData


ORIENTATIONS = tuple(itertools.product((False, True), repeat=3))


def oriented(array, orientation):
    horizontal, vertical, transpose = orientation
    result = array.T if transpose else array
    if horizontal:
        result = result[:, ::-1]
    if vertical:
        result = result[::-1, :]
    return result


def pixels(image):
    return np.array([
        [image.pixelColor(x, y).red() for x in range(image.width())]
        for y in range(image.height())
    ], dtype=np.uint8)


class TestSampledPreviewIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = QSettings(str(Path(temporary.name) / 'sampled-preview.ini'), QSettings.Format.IniFormat)
        settings_patch = patch('astroview.app.main_window.QSettings', return_value=settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.window = MainWindow()
        self.window.initialize(apply_startup_request=False)
        self.window.fits_service.set_interval('MinMax')
        # Deliver results deterministically through production handlers while
        # leaving session activation, orientation and canvas presentation real.
        for name in ('_schedule_frame_render', '_prewarm_adjacent_frame', '_schedule_next_composite_dirty_frame'):
            scheduler_patch = patch.object(self.window, name)
            scheduler_patch.start()
            self.addCleanup(scheduler_patch.stop)
        self.addCleanup(self._close_window)

    def _close_window(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _load(self, width=7, height=5, step=2, offset=0):
        data_array = np.arange(width * height, dtype=np.float32).reshape(height, width) + offset
        data = FITSData(path=f'preview-{offset}.fits', data=data_array)
        texture = np.asarray(data_array[::step, ::step] % 256, dtype=np.uint8)
        spec = ResolvedRenderSpec('Linear', 'MinMax', (float(data_array.min()), float(data_array.max())))
        payload = RenderResult(texture, width, height, sample_step=step, resolved_spec=spec)
        self.window._handle_loaded_frame(data, payload)
        expanded = np.repeat(np.repeat(texture, step, axis=0), step, axis=1)[:height, :width]
        return data, payload, expanded

    def _accept_request(self, index=0, request_id=50, generation=7):
        self.window._render_generation = generation
        self.window._latest_render_request_by_index[index] = request_id
        return request_id, generation, index

    def test_load_keeps_sampled_texture_and_raw_export_matches_all_orientations(self):
        data, payload, expanded = self._load()
        frame = self.window._session[0]
        self.assertIs(frame.data, data)
        self.assertEqual((frame.image.width(), frame.image.height()), (4, 3))
        self.assertEqual(frame.sample_step, 2)
        self.assertIs(frame.resolved_spec, payload.resolved_spec)
        self.assertTrue(frame.dirty)
        self.assertGreater(frame.preview_dimension, 0)
        for orientation in ORIENTATIONS:
            with self.subTest(orientation=orientation):
                self.window._set_orientation(orientation)
                raw = self.window._visual_image_for_export(with_annotations=False)
                expected = oriented(expanded, orientation)
                np.testing.assert_array_equal(pixels(raw), expected)
                annotated = self.window._visual_image_for_export(with_annotations=True)
                np.testing.assert_array_equal(pixels(annotated), expected)
                state = self.window.canvas.capture_view_state()
                self.assertEqual((state['image_width'], state['image_height']), expected.shape[::-1])
        # Serialization uses the expanded display extent but never expands cache.
        self.assertEqual((frame.image.width(), frame.image.height()), (4, 3))

    def test_preview_then_full_result_preserves_zoom_and_pan_with_transpose_flip(self):
        data, initial, _ = self._load(width=801, height=501, step=4)
        self.window._set_orientation((True, False, True))
        canvas = self.window.canvas
        canvas.resize(400, 300)
        canvas.show()
        canvas.resetTransform()
        canvas.scale(1.7, 1.7)
        canvas.set_zoom_state(ZoomState(scale_factor=1.7, mode='custom'))
        canvas.centerOn(330, 530)
        self.app.processEvents()
        before = canvas.capture_view_state()
        scroll_before = (canvas.horizontalScrollBar().value(), canvas.verticalScrollBar().value())
        request = self._accept_request()

        finer_texture = np.asarray(data.data[::2, ::2] % 256, dtype=np.uint8)
        finer = RenderResult(finer_texture, 801, 501, sample_step=2, resolved_spec=initial.resolved_spec)
        self.window._handle_frame_preview_rendered(*request, finer)
        self.assertEqual(self.window._session[0].sample_step, 2)
        self.assertTrue(self.window._session[0].dirty)
        self.assertEqual(canvas.capture_view_state(), before)

        full = RenderResult(np.asarray(data.data % 256, dtype=np.uint8), 801, 501, resolved_spec=initial.resolved_spec)
        self.window._handle_frame_rendered(*request, full)
        self.app.processEvents()
        self.assertEqual(self.window._session[0].sample_step, 1)
        self.assertFalse(self.window._session[0].dirty)
        self.assertIs(self.window._session[0].resolved_spec, initial.resolved_spec)
        self.assertEqual(canvas.capture_view_state(), before)
        self.assertEqual((canvas.horizontalScrollBar().value(), canvas.verticalScrollBar().value()), scroll_before)

    def test_composite_exports_crop_sample_blocks_and_align_every_orientation(self):
        first_data, _, first = self._load(width=7, height=5, step=2)
        second_data, _, second = self._load(width=5, height=7, step=3, offset=80)
        for layout in ('tiled', 'vertical'):
            self.window._frame_layout_mode = layout
            for orientation in ORIENTATIONS:
                with self.subTest(layout=layout, orientation=orientation):
                    self.window._orientation = orientation
                    first_image = oriented(first, orientation)
                    second_image = oriented(second, orientation)
                    h1, w1 = first_image.shape
                    h2, w2 = second_image.shape
                    if layout == 'tiled':
                        expected = np.zeros((max(h1, h2), w1 + w2), dtype=np.uint8)
                        x2, y2 = w1, 0
                    else:
                        expected = np.zeros((h1 + h2, max(w1, w2)), dtype=np.uint8)
                        x2, y2 = 0, h1
                    expected[:h1, :w1] = first_image
                    expected[y2:y2+h2, x2:x2+w2] = second_image
                    self.window._show_current_frame_image()
                    for annotations in (False, True):
                        actual = self.window._visual_image_for_export(with_annotations=annotations)
                        np.testing.assert_array_equal(pixels(actual), expected)
                    first_sample = self.window._sample_composite_frame(0, 0)
                    second_sample = self.window._sample_composite_frame(x2, y2)
                    self.assertEqual(first_sample.value, oriented(first_data.data, orientation)[0, 0])
                    self.assertEqual(second_sample.value, oriented(second_data.data, orientation)[0, 0])

    def test_stale_render_cannot_replace_pixels_or_sampling_metadata(self):
        _, initial, expanded = self._load()
        request_id, generation, index = self._accept_request()
        frame = self.window._session[index]
        original_image = frame.image
        stale = RenderResult(
            np.full((1, 1), 255, dtype=np.uint8), 7, 5, sample_step=8,
            resolved_spec=ResolvedRenderSpec('Log', 'Manual', (10.0, 20.0)),
        )
        for handler in (self.window._handle_frame_preview_rendered, self.window._handle_frame_rendered):
            for request in ((request_id - 1, generation, index), (request_id, generation - 1, index), (request_id, generation, -1)):
                with self.subTest(handler=handler.__name__, request=request):
                    handler(*request, stale)
                    self.assertIs(frame.image, original_image)
                    self.assertEqual(frame.sample_step, 2)
                    self.assertIs(frame.resolved_spec, initial.resolved_spec)
                    self.assertTrue(frame.dirty)
                    np.testing.assert_array_equal(pixels(self.window._visual_image_for_export(with_annotations=False)), expanded)

    def test_loaded_preview_with_old_display_preferences_keeps_data_without_stale_image(self):
        # Simulate a control change while the loader is still rendering its
        # captured Linear preview; accepting the FITS data must remain possible.
        self.window.fits_service.set_stretch('Log')
        data, _, _ = self._load()
        frame = self.window._session[0]
        self.assertIs(frame.data, data)
        self.assertIsNone(frame.image)
        self.assertIsNone(frame.resolved_spec)
        self.assertEqual(frame.sample_step, 1)
        self.assertEqual(frame.preview_dimension, 0)
        self.assertTrue(frame.dirty)
        self.assertIsNone(self.window.canvas.current_image)
        self.window._schedule_frame_render.assert_called_with(0)


if __name__ == '__main__':
    unittest.main()
