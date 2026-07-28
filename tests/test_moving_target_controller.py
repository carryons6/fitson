from __future__ import annotations

import gc
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication


REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.moving_target_controller import MovingTargetController
from astroview.core.contracts import ROISelection
from astroview.core.fits_data import FITSData
from astroview.core.moving_targets import MovingTargetParameters


def _frames(count: int = 5) -> list[FITSData]:
    return [
        FITSData(path=f"frame-{index}.fits", data=np.zeros((40, 60), dtype=np.float32))
        for index in range(count)
    ]


class TestMovingTargetController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_roi_capture_is_one_shot_and_full_frame_clears_result(self) -> None:
        controller = MovingTargetController()
        cleared: list[bool] = []
        controller.result_cleared.connect(lambda: cleared.append(True))
        controller.result = Mock()

        roi = ROISelection(3, 4, 20, 18)
        controller.begin_roi_capture()
        self.assertTrue(controller.consume_captured_roi(roi))
        self.assertFalse(controller.capture_pending)
        self.assertEqual(controller.roi, roi)
        self.assertIsNone(controller.result)
        self.assertFalse(controller.consume_captured_roi(ROISelection(0, 0, 10, 10)))

        controller.result = Mock()
        controller.use_full_frame()
        self.assertIsNone(controller.roi)
        self.assertIsNone(controller.result)
        self.assertEqual(len(cleared), 2)

    def test_start_owns_request_identity_and_worker_lifecycle(self) -> None:
        controller = MovingTargetController()
        started: list[bool] = []
        finished: list[bool] = []
        controller.detection_started.connect(lambda: started.append(True))
        controller.detection_finished.connect(finished.append)
        frames = _frames()

        with patch("astroview.app.moving_target_controller.QThread.start", autospec=True) as start:
            accepted = controller.start(
                frames=frames,
                roi=ROISelection(0, 0, 60, 40),
                parameters=MovingTargetParameters(),
                fallback_cadence_seconds=1.0,
                prefer_header_times=False,
            )

        self.assertTrue(accepted)
        self.assertEqual(started, [True])
        self.assertEqual(controller.request_id, 1)
        self.assertEqual(controller.active_request_id, 1)
        self.assertTrue(controller.results_enabled)
        self.assertIsNotNone(controller.thread)
        self.assertIsNotNone(controller.worker)
        start.assert_called_once()

        thread = controller.thread
        worker = controller.worker
        assert thread is not None and worker is not None
        controller.clear_worker_refs(1, thread, worker)
        self.assertIsNone(controller.thread)
        self.assertIsNone(controller.worker)
        self.assertEqual(finished, [False])

    def test_context_and_dataset_identity_reject_stale_callbacks(self) -> None:
        controller = MovingTargetController()
        frames = _frames()
        controller.sync_sequence(frames)
        worker = Mock()
        controller.worker = worker
        controller.active_request_id = 7
        controller.context_generation = 3
        controller.results_enabled = True
        signature = controller.current_dataset_signature()
        accepted: list[object] = []
        controller.result_accepted.connect(accepted.append)
        result = Mock()

        controller.handle_result_for_request(7, 2, signature, worker, result)
        controller.handle_result_for_request(7, 3, signature[:-1], worker, result)
        self.assertEqual(accepted, [])
        self.assertIsNone(controller.result)

        controller.handle_result_for_request(7, 3, signature, worker, result)
        self.assertEqual(accepted, [result])
        self.assertIs(controller.result, result)

        controller.result = None
        controller.sync_sequence([*frames, FITSData(path="new.fits", data=np.zeros((40, 60)))])
        controller.handle_result_for_request(7, 3, signature, worker, result)
        self.assertIsNone(controller.result)

    def test_sequence_identity_does_not_retain_frame_arrays(self) -> None:
        controller = MovingTargetController()

        class WeakFrame:
            pass

        frame = WeakFrame()
        frame.data = np.zeros((40, 60), dtype=np.float32)
        frame_ref = weakref.ref(frame)

        controller.sync_sequence([frame])
        self.assertEqual(controller.current_dataset_signature(), (id(frame),))
        del frame
        gc.collect()

        self.assertIsNone(frame_ref())

    def test_cancel_rejects_already_queued_result_progress_and_error(self) -> None:
        controller = MovingTargetController()
        frames = _frames()
        controller.sync_sequence(frames)
        signature = controller.current_dataset_signature()
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        controller.thread = thread
        controller.worker = worker
        controller.active_request_id = 4
        controller.context_generation = 2
        controller.results_enabled = True
        results: list[object] = []
        progress: list[tuple[int, int, str]] = []
        errors: list[str] = []
        controller.result_accepted.connect(results.append)
        controller.progress_accepted.connect(lambda *args: progress.append(args))
        controller.error_accepted.connect(errors.append)

        self.assertFalse(controller.cancel(wait=False))
        controller.handle_result_for_request(4, 2, signature, worker, Mock())
        controller.handle_progress_for_request(4, 2, signature, worker, 1, 5, "queued")
        controller.handle_error_for_request(4, 2, signature, worker, "queued")

        worker.cancel.assert_called_once()
        thread.requestInterruption.assert_called_once()
        thread.quit.assert_called_once()
        self.assertEqual(results, [])
        self.assertEqual(progress, [])
        self.assertEqual(errors, [])

    def test_wait_timeout_keeps_running_thread_tracked(self) -> None:
        controller = MovingTargetController(join_wait_ms=123)
        thread = Mock()
        thread.isRunning.return_value = True
        thread.wait.return_value = False
        worker = Mock()
        controller.thread = thread
        controller.worker = worker
        controller.active_request_id = 9
        controller.results_enabled = True

        self.assertFalse(controller.stop(wait=True))
        self.assertIs(controller.thread, thread)
        self.assertIs(controller.worker, worker)
        self.assertEqual(controller.active_request_id, 9)
        thread.wait.assert_called_once_with(123)

    def test_invalidate_preserves_or_clears_roi_as_requested(self) -> None:
        controller = MovingTargetController()
        roi = ROISelection(2, 3, 20, 16)
        controller.roi = roi
        controller.result = Mock()
        controller.invalidate_sequence(clear_roi=False)
        self.assertEqual(controller.roi, roi)
        self.assertIsNone(controller.result)

        controller.result = Mock()
        controller.invalidate_sequence(clear_roi=True)
        self.assertIsNone(controller.roi)
        self.assertIsNone(controller.result)


if __name__ == "__main__":
    unittest.main()
