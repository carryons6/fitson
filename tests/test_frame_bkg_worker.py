from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.frame_bkg_worker import FrameBkgWorker
from astroview.core.sep_service import SEPParameters


class _FakeThread:
    def __init__(self, interrupted: bool = False) -> None:
        self.interrupted = interrupted

    def isInterruptionRequested(self) -> bool:
        return self.interrupted


class TestFrameBkgWorker(unittest.TestCase):
    def test_cancel_before_run_suppresses_compute_and_result_but_finishes(self) -> None:
        service = Mock()
        worker = FrameBkgWorker(
            frame_index=2,
            generation=7,
            data=np.zeros((2, 2)),
            sep_service=service,
            params=SEPParameters(),
        )
        ready = []
        finished = []
        worker.bkg_ready.connect(lambda *args: ready.append(args))
        worker.finished.connect(finished.append)
        worker.cancel()

        with patch(
            "astroview.app.frame_bkg_worker.QThread.currentThread",
            return_value=_FakeThread(),
        ):
            worker.run()

        service.compute_background.assert_not_called()
        self.assertEqual(ready, [])
        self.assertEqual(finished, [2])

    def test_cancel_during_compute_suppresses_late_background_result(self) -> None:
        service = Mock()
        worker = FrameBkgWorker(
            frame_index=1,
            generation=3,
            data=np.zeros((2, 2)),
            sep_service=service,
            params=SEPParameters(),
        )
        ready = []
        finished = []
        worker.bkg_ready.connect(lambda *args: ready.append(args))
        worker.finished.connect(finished.append)

        def compute(_data, _params):
            worker.cancel()
            values = np.ones((2, 2), dtype=np.float32)
            return values, values, 1.0

        service.compute_background.side_effect = compute
        with patch(
            "astroview.app.frame_bkg_worker.QThread.currentThread",
            return_value=_FakeThread(),
        ):
            worker.run()

        self.assertEqual(ready, [])
        self.assertEqual(finished, [1])


if __name__ == "__main__":
    unittest.main()
