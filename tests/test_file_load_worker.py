from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.file_load_worker import FITSLoadWorker
from astroview.core.fits_data import FITSData


class _FakeThread:
    def __init__(self) -> None:
        self.interrupted = False

    def isInterruptionRequested(self) -> bool:
        return self.interrupted


class TestFITSLoadWorker(unittest.TestCase):
    def test_run_emits_loaded_progress_and_finished(self) -> None:
        worker = FITSLoadWorker(["a.fits", "b.fits"], hdu_index=3, source_group_start=10)
        loaded: list[tuple[FITSData, object]] = []
        progress: list[tuple[int, int, str]] = []
        finished: list[bool] = []

        worker.file_loaded.connect(lambda data, preview: loaded.append((data, preview)))
        worker.progress.connect(lambda done, total, path: progress.append((done, total, path)))
        worker.finished.connect(lambda: finished.append(True))

        with patch("astroview.app.file_load_worker.QThread.currentThread", return_value=_FakeThread()):
            with patch(
                "astroview.app.file_load_worker.FITSData.load_frames",
                side_effect=lambda path, hdu_index, source_group_id=None: [
                    FITSData(path=path, hdu_index=hdu_index, source_group_id=source_group_id),
                ],
            ) as load_mock:
                worker.run()

        self.assertEqual([item.path for item, _ in loaded], ["a.fits", "b.fits"])
        self.assertIsNone(loaded[0][1])
        self.assertIsNone(loaded[1][1])
        self.assertEqual(progress, [(1, 2, "a.fits"), (2, 2, "b.fits")])
        self.assertEqual(finished, [True])
        self.assertEqual(load_mock.call_count, 2)
        self.assertEqual(load_mock.call_args_list[0].args, ("a.fits", 3))
        self.assertEqual(load_mock.call_args_list[0].kwargs, {"source_group_id": 10})
        self.assertEqual(load_mock.call_args_list[1].args, ("b.fits", 3))
        self.assertEqual(load_mock.call_args_list[1].kwargs, {"source_group_id": 11})

    def test_run_emits_error_and_continues(self) -> None:
        worker = FITSLoadWorker(["bad.fits", "good.fits"])
        errors: list[tuple[str, str]] = []
        progress: list[tuple[int, int, str]] = []
        loaded: list[tuple[FITSData, object]] = []

        worker.file_error.connect(lambda path, detail: errors.append((path, detail)))
        worker.file_loaded.connect(lambda data, preview: loaded.append((data, preview)))
        worker.progress.connect(lambda done, total, path: progress.append((done, total, path)))

        def side_effect(path: str, hdu_index: int | None, source_group_id: int | None = None) -> list[FITSData]:
            if path == "bad.fits":
                raise ValueError("broken")
            return [FITSData(path=path, hdu_index=hdu_index, source_group_id=source_group_id)]

        with patch("astroview.app.file_load_worker.QThread.currentThread", return_value=_FakeThread()):
            with patch("astroview.app.file_load_worker.FITSData.load_frames", side_effect=side_effect):
                worker.run()

        self.assertEqual(errors, [("bad.fits", "broken")])
        self.assertEqual([item.path for item, _ in loaded], ["good.fits"])
        self.assertIsNone(loaded[0][1])
        self.assertEqual(progress, [(1, 2, "bad.fits"), (2, 2, "good.fits")])

    def test_run_stops_after_interruption_is_requested(self) -> None:
        fake_thread = _FakeThread()
        worker = FITSLoadWorker(["one.fits", "two.fits", "three.fits"])
        loaded: list[tuple[FITSData, object]] = []
        progress: list[tuple[int, int, str]] = []

        worker.file_loaded.connect(lambda data, preview: loaded.append((data, preview)))
        worker.progress.connect(lambda done, total, path: progress.append((done, total, path)))

        def side_effect(path: str, hdu_index: int | None, source_group_id: int | None = None) -> list[FITSData]:
            fake_thread.interrupted = True
            return [FITSData(path=path, hdu_index=hdu_index, source_group_id=source_group_id)]

        with patch("astroview.app.file_load_worker.QThread.currentThread", return_value=fake_thread):
            with patch("astroview.app.file_load_worker.FITSData.load_frames", side_effect=side_effect):
                worker.run()

        self.assertEqual([item.path for item, _ in loaded], ["one.fits"])
        self.assertIsNone(loaded[0][1])
        self.assertEqual(progress, [(1, 3, "one.fits")])

    def test_run_renders_preview_for_first_successful_frame_only(self) -> None:
        worker = FITSLoadWorker(["a.fits", "b.fits"], preview_first_frame=True)
        loaded: list[tuple[FITSData, object]] = []

        worker.file_loaded.connect(lambda data, preview: loaded.append((data, preview)))

        with patch("astroview.app.file_load_worker.QThread.currentThread", return_value=_FakeThread()):
            with patch(
                "astroview.app.file_load_worker.FITSData.load_frames",
                side_effect=lambda path, hdu_index, source_group_id=None: [
                    FITSData(path=path, hdu_index=hdu_index, source_group_id=source_group_id),
                ],
            ):
                with patch.object(worker, "_render_preview", side_effect=["preview-u8"]) as render_mock:
                    worker.run()

        self.assertEqual([item.path for item, _ in loaded], ["a.fits", "b.fits"])
        self.assertEqual(loaded[0][1], "preview-u8")
        self.assertIsNone(loaded[1][1])
        render_mock.assert_called_once()

    def test_run_renders_preview_for_every_frame_when_enabled(self) -> None:
        worker = FITSLoadWorker(["a.fits", "b.fits"], preview_each_frame=True)
        loaded: list[tuple[FITSData, object]] = []

        worker.file_loaded.connect(lambda data, preview: loaded.append((data, preview)))

        with patch("astroview.app.file_load_worker.QThread.currentThread", return_value=_FakeThread()):
            with patch(
                "astroview.app.file_load_worker.FITSData.load_frames",
                side_effect=lambda path, hdu_index, source_group_id=None: [
                    FITSData(path=path, hdu_index=hdu_index, source_group_id=source_group_id),
                ],
            ):
                with patch.object(worker, "_render_preview", side_effect=["preview-a", "preview-b"]) as render_mock:
                    worker.run()

        self.assertEqual([item.path for item, _ in loaded], ["a.fits", "b.fits"])
        self.assertEqual([preview for _, preview in loaded], ["preview-a", "preview-b"])
        self.assertEqual(render_mock.call_count, 2)

    def test_run_emits_one_loaded_signal_per_cube_frame(self) -> None:
        worker = FITSLoadWorker(["cube.fits"], preview_each_frame=True)
        loaded: list[tuple[FITSData, object]] = []
        progress: list[tuple[int, int, str]] = []

        worker.file_loaded.connect(lambda data, preview: loaded.append((data, preview)))
        worker.progress.connect(lambda done, total, path: progress.append((done, total, path)))

        frames = [
            FITSData(path="cube.fits", data=np.zeros((2, 2)), frame_index=0, frame_count=3, source_group_id=0),
            FITSData(path="cube.fits", data=np.ones((2, 2)), frame_index=1, frame_count=3, source_group_id=0),
            FITSData(path="cube.fits", data=np.full((2, 2), 2.0), frame_index=2, frame_count=3, source_group_id=0),
        ]

        with patch("astroview.app.file_load_worker.QThread.currentThread", return_value=_FakeThread()):
            with patch("astroview.app.file_load_worker.FITSData.load_frames", return_value=frames):
                with patch.object(worker, "_render_preview", side_effect=["preview-0", "preview-1", "preview-2"]):
                    worker.run()

        self.assertEqual([item.frame_index for item, _ in loaded], [0, 1, 2])
        self.assertEqual([preview for _, preview in loaded], ["preview-0", "preview-1", "preview-2"])
        self.assertEqual(progress, [(1, 1, "cube.fits")])


if __name__ == "__main__":
    unittest.main()
