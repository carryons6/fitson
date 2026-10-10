from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.frame_render_worker import FrameRenderWorker
from astroview.core.contracts import RenderResult, ResolvedRenderSpec
from astroview.core.fits_data import FITSData


class _FakeThread:
    def __init__(self) -> None:
        self.interrupted = False

    def isInterruptionRequested(self) -> bool:
        return self.interrupted


class TestFrameRenderWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_sampled_previews_keep_logical_extent_and_match_full_render(self) -> None:
        worker = FrameRenderWorker(
            request_id=4,
            generation=2,
            frame_index=1,
            data=FITSData(data=np.arange(35, dtype=np.float32).reshape(5, 7)),
            stretch_name="Linear",
            interval_name="Original",
            preview_dimensions=(2, 3),
            sampled_previews=True,
        )
        previews = []
        renders = []
        worker.preview_ready.connect(lambda req, gen, idx, image: previews.append(image))
        worker.render_ready.connect(lambda req, gen, idx, image: renders.append(image))

        with patch("astroview.app.frame_render_worker.QThread.currentThread", return_value=_FakeThread()):
            worker.run()

        self.assertEqual(len(previews), 2)
        self.assertEqual(len(renders), 1)
        full = renders[0]
        self.assertIsInstance(full, RenderResult)
        self.assertEqual((full.width, full.height, full.sample_step), (7, 5, 1))
        for preview in previews:
            self.assertIsInstance(preview, RenderResult)
            self.assertEqual((preview.width, preview.height), (7, 5))
            step = preview.sample_step
            np.testing.assert_array_equal(preview.image_u8, full.image_u8[::step, ::step])
            self.assertIs(preview.resolved_spec, full.resolved_spec)
        self.assertIs(previews[0].resolved_spec, previews[1].resolved_spec)

    def test_cached_loading_spec_is_reused_for_preview_and_final_without_estimation(self) -> None:
        spec = ResolvedRenderSpec("Linear", "Original", (0.0, 100.0))
        worker = FrameRenderWorker(
            request_id=1, generation=1, frame_index=0,
            data=FITSData(data=np.arange(35, dtype=np.float32).reshape(5, 7)),
            stretch_name="Linear", interval_name="Original", preview_dimensions=(3,),
            sampled_previews=True, resolved_spec=spec,
        )
        previews = []
        renders = []
        errors = []
        worker.preview_ready.connect(lambda req, gen, idx, image: previews.append(image))
        worker.render_ready.connect(lambda req, gen, idx, image: renders.append(image))
        worker.render_error.connect(lambda req, gen, idx, detail: errors.append(detail))

        with patch("astroview.app.frame_render_worker.compute_interval_limits", side_effect=AssertionError("recomputed")) as compute_mock:
            worker.run()

        self.assertEqual(errors, [])
        compute_mock.assert_not_called()
        self.assertEqual((len(previews), len(renders)), (1, 1))
        self.assertIs(previews[0].resolved_spec, spec)
        self.assertIs(renders[0].resolved_spec, spec)
        self.assertEqual(renders[0].sample_step, 1)
        # The pre-existing 0..100 mapping remains, even though this frame's
        # brightest source pixel is 34 and re-estimation would turn it white.
        self.assertEqual(renders[0].image_u8[-1, -1], 86)

    def test_constant_and_empty_limits_are_resolved_once_without_manual_conversion(self) -> None:
        for limits in ((7.0, 7.0), None):
            with self.subTest(limits=limits):
                worker = FrameRenderWorker(
                    request_id=1, generation=1, frame_index=0,
                    data=FITSData(data=np.ones((4, 4))),
                    stretch_name="Linear", interval_name="Original",
                    preview_dimensions=(1, 2),
                )
                with patch("astroview.app.frame_render_worker.compute_interval_limits", return_value=limits) as interval_mock:
                    with patch("astroview.app.frame_render_worker.render_preview_u8", return_value=None) as preview_mock:
                        with patch("astroview.app.frame_render_worker.render_image_u8", return_value=None) as full_mock:
                            worker.run()
                interval_mock.assert_called_once()
                spec = full_mock.call_args.kwargs["resolved_spec"]
                self.assertEqual(spec.interval_name, "Original")
                self.assertEqual(spec.limits, limits)
                for call in preview_mock.call_args_list:
                    self.assertIs(call.kwargs["resolved_spec"], spec)

    def test_run_emits_multi_stage_previews_then_full_render(self) -> None:
        worker = FrameRenderWorker(
            request_id=7,
            generation=2,
            frame_index=3,
            data=FITSData(path="demo.fits"),
            stretch_name="Linear",
            interval_name="ZScale",
        )
        previews: list[tuple[int, int, int, object]] = []
        renders: list[tuple[int, int, int, object]] = []
        finished: list[int] = []

        worker.preview_ready.connect(lambda req, gen, idx, img: previews.append((req, gen, idx, img)))
        worker.render_ready.connect(lambda req, gen, idx, img: renders.append((req, gen, idx, img)))
        worker.finished.connect(finished.append)

        with patch("astroview.app.frame_render_worker.QThread.currentThread", return_value=_FakeThread()):
            with patch(
                "astroview.app.frame_render_worker.render_preview_u8",
                side_effect=["preview-1024", "preview-2048"],
            ) as preview_mock:
                with patch("astroview.app.frame_render_worker.render_image_u8", return_value="full") as full_mock:
                    worker.run()

        self.assertEqual(
            previews,
            [
                (7, 2, 3, "preview-1024"),
                (7, 2, 3, "preview-2048"),
            ],
        )
        self.assertEqual(renders, [(7, 2, 3, "full")])
        self.assertEqual(finished, [7])
        self.assertEqual(preview_mock.call_count, 2)
        self.assertEqual(preview_mock.call_args_list[0].kwargs["max_dimension"], 1024)
        self.assertEqual(preview_mock.call_args_list[1].kwargs["max_dimension"], 2048)
        full_mock.assert_called_once()

    def test_run_skips_full_render_after_interruption(self) -> None:
        fake_thread = _FakeThread()
        worker = FrameRenderWorker(
            request_id=1,
            generation=1,
            frame_index=0,
            data=FITSData(path="demo.fits"),
            stretch_name="Linear",
            interval_name="ZScale",
        )
        renders: list[tuple[int, int, int, object]] = []

        worker.render_ready.connect(lambda req, gen, idx, img: renders.append((req, gen, idx, img)))

        def preview_side_effect(*args, **kwargs):
            fake_thread.interrupted = True
            return "preview"

        with patch("astroview.app.frame_render_worker.QThread.currentThread", return_value=fake_thread):
            with patch("astroview.app.frame_render_worker.render_preview_u8", side_effect=preview_side_effect):
                with patch("astroview.app.frame_render_worker.render_image_u8") as full_mock:
                    worker.run()

        self.assertEqual(renders, [])
        full_mock.assert_not_called()

    def test_run_skips_missing_preview_stages_and_continues(self) -> None:
        worker = FrameRenderWorker(
            request_id=5,
            generation=1,
            frame_index=2,
            data=FITSData(path="demo.fits"),
            stretch_name="Linear",
            interval_name="ZScale",
        )
        previews: list[tuple[int, int, int, object]] = []
        renders: list[tuple[int, int, int, object]] = []

        worker.preview_ready.connect(lambda req, gen, idx, img: previews.append((req, gen, idx, img)))
        worker.render_ready.connect(lambda req, gen, idx, img: renders.append((req, gen, idx, img)))

        with patch("astroview.app.frame_render_worker.QThread.currentThread", return_value=_FakeThread()):
            with patch(
                "astroview.app.frame_render_worker.render_preview_u8",
                side_effect=[None, "preview-2048"],
            ):
                with patch("astroview.app.frame_render_worker.render_image_u8", return_value="full"):
                    worker.run()

        self.assertEqual(previews, [(5, 1, 2, "preview-2048")])
        self.assertEqual(renders, [(5, 1, 2, "full")])

    def test_run_emits_signals_across_real_qthread(self) -> None:
        worker = FrameRenderWorker(
            request_id=9,
            generation=4,
            frame_index=1,
            data=FITSData(path="threaded-demo.fits"),
            stretch_name="Linear",
            interval_name="ZScale",
        )
        previews: list[tuple[int, int, int, object]] = []
        renders: list[tuple[int, int, int, object]] = []
        errors: list[tuple[int, int, int, str]] = []
        finished: list[int] = []

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.preview_ready.connect(lambda req, gen, idx, img: previews.append((req, gen, idx, img)))
        worker.render_ready.connect(lambda req, gen, idx, img: renders.append((req, gen, idx, img)))
        worker.render_error.connect(lambda req, gen, idx, detail: errors.append((req, gen, idx, detail)))
        worker.finished.connect(finished.append)
        worker.finished.connect(thread.quit)

        loop = QEventLoop()
        thread.finished.connect(loop.quit)
        QTimer.singleShot(3000, loop.quit)

        try:
            with patch(
                "astroview.app.frame_render_worker.render_preview_u8",
                side_effect=["preview-1024", "preview-2048"],
            ) as preview_mock:
                with patch(
                    "astroview.app.frame_render_worker.render_image_u8",
                    return_value="full-threaded",
                ) as full_mock:
                    thread.start()
                    loop.exec()

            self.assertFalse(thread.isRunning(), "FrameRenderWorker thread did not finish in time.")
            self.assertEqual(
                previews,
                [
                    (9, 4, 1, "preview-1024"),
                    (9, 4, 1, "preview-2048"),
                ],
            )
            self.assertEqual(renders, [(9, 4, 1, "full-threaded")])
            self.assertEqual(errors, [])
            self.assertEqual(finished, [9])
            self.assertEqual(preview_mock.call_count, 2)
            full_mock.assert_called_once()
        finally:
            thread.quit()
            thread.wait(1000)
            worker.deleteLater()


if __name__ == "__main__":
    unittest.main()
