from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from astroview.app.frame_session import FrameSession
from astroview.app.main_window import MainWindow
from astroview.core.contracts import RenderResult, ResolvedRenderSpec
from astroview.core.fits_data import FITSData
from astroview.core.fits_service import resolve_render_spec


class TestRenderStateIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.window._view_mode = "original"
        self.window.fits_service.set_stretch("Linear")
        self.window.fits_service.set_interval("Original")
        self.window.fits_service.clear_manual_interval_limits()
        self.window._histogram_axis_limits = None

    def _set_frame(self, data: FITSData) -> None:
        self.window._session = FrameSession([data])
        self.window.fits_service.current_data = data

    def test_late_loader_previews_with_stale_controls_are_not_cached(self) -> None:
        frame = FITSData(data=np.arange(16, dtype=np.float32).reshape(4, 4))
        cases = (
            ("Asinh", "Original", None, ResolvedRenderSpec("Linear", "Original", (0.0, 15.0))),
            ("Linear", "MinMax", None, ResolvedRenderSpec("Linear", "Original", (0.0, 15.0))),
            ("Linear", "Manual", (10.0, 20.0), ResolvedRenderSpec("Linear", "Manual", (0.0, 10.0))),
        )
        # An earlier loaded frame makes the render controls available while
        # the loader continues using the configuration it started with.
        self._set_frame(FITSData(data=np.zeros((4, 4))))
        for name in (
            "_sync_frame_player", "_sync_comparison_inputs", "_sync_moving_target_context",
            "_schedule_next_composite_dirty_frame",
        ):
            setattr(self.window, name, Mock())
        for stretch, interval, limits, old_spec in cases:
            with self.subTest(stretch=stretch, interval=interval):
                self.window.fits_service.set_stretch(stretch)
                self.window.fits_service.set_interval(interval)
                self.window.fits_service.clear_manual_interval_limits()
                if limits is not None:
                    self.window.fits_service.set_manual_interval_limits(*limits)
                preview = RenderResult(
                    np.zeros((2, 2), dtype=np.uint8), width=4, height=4,
                    sample_step=2, resolved_spec=old_spec,
                )
                self.window._handle_loaded_frame(frame, preview)
                loaded = self.window._session[-1]
                self.assertIs(loaded.data, frame)
                self.assertIsNone(loaded.image)
                self.assertIsNone(loaded.resolved_spec)
                self.assertEqual(loaded.preview_dimension, 0)
                self.assertTrue(loaded.dirty)

    def test_histogram_reuses_current_mapping_without_interval_estimation(self) -> None:
        data = FITSData(data=np.array([[1.0, 2.0], [3.0, 4.0]]))
        self._set_frame(data)
        spec = resolve_render_spec(data, "Linear", "Original")
        self.window._session[0].resolved_spec = spec
        dock = Mock()
        dock.isVisible.return_value = True
        self.window.histogram_dock = dock

        with patch.object(self.window.fits_service, "resolve_render_spec", side_effect=AssertionError("recomputed")) as resolve:
            self.window._refresh_histogram_view()

        resolve.assert_not_called()
        counts, low, high = dock.set_histogram.call_args.args
        self.assertEqual((low, high), spec.limits)
        self.assertEqual(counts.sum(), 4)

    def test_background_and_residual_histograms_use_displayed_data(self) -> None:
        original = FITSData(data=np.array([[100.0, 200.0], [1000.0, 2000.0]]))
        for mode, values in (
            ("background", [[1.0, 2.0], [3.0, 4.0]]),
            ("residual", [[-4.0, -2.0], [0.0, 2.0]]),
        ):
            for use_cache in (False, True):
                with self.subTest(mode=mode, cached=use_cache):
                    self._set_frame(original)
                    displayed = FITSData(data=np.asarray(values))
                    self.window._view_mode = mode
                    setattr(self.window._session[0], mode, displayed)
                    spec = resolve_render_spec(displayed, "Linear", "Original")
                    self.window._session[0].resolved_spec = spec if use_cache else None
                    dock = Mock()
                    dock.isVisible.return_value = True
                    self.window.histogram_dock = dock
                    service = self.window.fits_service
                    with patch.object(service, "histogram", wraps=service.histogram) as histogram:
                        self.window._refresh_histogram_view()

                    self.assertIs(histogram.call_args.args[0], displayed)
                    counts, low, high = dock.set_histogram.call_args.args
                    self.assertEqual((low, high), spec.limits)
                    self.assertEqual(counts.sum(), 4)
                    self.assertIs(service.current_data, original)

    def test_manual_histogram_keeps_prior_auto_axis_while_handles_change(self) -> None:
        data = FITSData(data=np.arange(6, dtype=np.float32).reshape(2, 3))
        self._set_frame(data)
        self.window.fits_service.set_interval("Manual")
        self.window.fits_service.set_manual_interval_limits(2.0, 4.0)
        self.window._session[0].resolved_spec = ResolvedRenderSpec("Linear", "Manual", (2.0, 4.0))
        self.window._histogram_axis_limits = (0.0, 5.0)
        dock = Mock()
        dock.isVisible.return_value = True
        self.window.histogram_dock = dock

        self.window._refresh_histogram_view()

        counts, low, high = dock.set_histogram.call_args.args
        self.assertEqual((low, high), (0.0, 5.0))
        self.assertEqual(counts.sum(), 6)
        self.assertEqual(dock.set_histogram.call_args.kwargs["manual_limits"], (2.0, 4.0))

    def test_active_render_callbacks_refresh_visible_histogram_from_new_mapping(self) -> None:
        original = FITSData(data=np.full((2, 2), 1000.0))
        displayed = FITSData(data=np.array([[1.0, 2.0], [3.0, 4.0]]))
        self._set_frame(original)
        self.window._session[0].background = displayed
        self.window._view_mode = "background"
        spec = resolve_render_spec(displayed, "Linear", "Original")
        payload = RenderResult(np.zeros((2, 2), dtype=np.uint8), width=2, height=2, resolved_spec=spec)
        dock = Mock()
        dock.isVisible.return_value = True
        self.window.histogram_dock = dock
        for name in ("_show_current_frame_image", "_sync_current_canvas_image_state", "_prewarm_adjacent_frame"):
            setattr(self.window, name, Mock())

        for callback in (self.window._handle_frame_preview_rendered, self.window._handle_frame_rendered):
            with self.subTest(callback=callback.__name__):
                dock.reset_mock()
                with patch.object(self.window, "_should_accept_render_result", return_value=True):
                    callback(1, 1, 0, payload)
                dock.set_histogram.assert_called_once()
                counts, low, high = dock.set_histogram.call_args.args
                self.assertEqual((low, high), (1.0, 4.0))
                self.assertEqual(counts.sum(), 4)

    def test_changing_mode_clears_histogram_while_background_is_unavailable(self) -> None:
        self._set_frame(FITSData(data=np.ones((2, 2))))
        dock = Mock()
        dock.isVisible.return_value = True
        self.window.histogram_dock = dock
        with patch.object(self.window, "_refresh_view_mode_indicators"):
            with patch.object(self.window, "_rerender_all_frames"):
                self.window._set_view_mode("background")

        dock.clear_histogram.assert_called_once()
        dock.set_histogram.assert_not_called()

    def test_rerender_invalidates_mapping_and_keeps_previous_texture_visible(self) -> None:
        data = FITSData(data=np.ones((4, 4)))
        self._set_frame(data)
        frame = self.window._session[0]
        image = QImage(2, 2, QImage.Format.Format_Grayscale8)
        frame.image = image
        frame.sample_step = 2
        frame.preview_dimension = 1024
        frame.resolved_spec = ResolvedRenderSpec("Linear", "Original", (1.0, 1.0))
        frame.dirty = False
        with patch.object(self.window, "_cancel_active_frame_renders"):
            with patch.object(self.window, "_sync_current_canvas_image_state"):
                with patch.object(self.window, "_ensure_frame_rendered") as ensure:
                    self.window._rerender_all_frames()

        self.assertIsNone(frame.resolved_spec)
        self.assertEqual(frame.preview_dimension, 0)
        self.assertTrue(frame.dirty)
        self.assertIs(frame.image, image)
        self.assertEqual(frame.sample_step, 2)
        ensure.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
