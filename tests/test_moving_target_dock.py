from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication


REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.moving_target_dock import MovingTargetDock
from astroview.core.contracts import ROISelection
from astroview.core.moving_targets import MovingTargetResult, MovingTargetTrack


def _result() -> MovingTargetResult:
    track = MovingTargetTrack(
        target_id=1,
        hit_frames=(0, 1, 2, 3, 4),
        x0=10.0,
        y0=20.0,
        vx=2.0,
        vy=0.5,
        rms=0.2,
        median_snr=5.0,
        positions=np.array([[10.0 + 2.0 * i, 20.0 + 0.5 * i] for i in range(5)]),
        measured_mask=np.ones(5, dtype=bool),
    )
    return MovingTargetResult(
        tracks=(track,),
        frame_count=5,
        roi=ROISelection(0, 0, 64, 64),
        seconds=np.arange(5, dtype=float),
        time_source="DATE-AVG",
        registration_shifts=np.zeros((5, 2)),
        registration_matches=(20,) * 5,
        registration_rms=(0.1,) * 5,
        source_counts=(30,) * 5,
        candidate_counts=(1,) * 5,
        static_source_count=25,
    )


class TestMovingTargetDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_context_controls_detection_enablement_and_typed_request(self) -> None:
        dock = MovingTargetDock()
        requests: list[tuple[object, float, bool]] = []
        dock.detection_requested.connect(
            lambda params, cadence, prefer: requests.append((params, cadence, prefer))
        )
        try:
            dock.set_input_context(4, (64, 64), None)
            self.assertFalse(dock.detect_button.isEnabled())
            dock.set_input_context(5, (64, 64), ROISelection(2, 3, 40, 30))
            self.assertTrue(dock.detect_button.isEnabled())
            dock.threshold_spin.setValue(4.5)
            dock.cadence_spin.setValue(2.25)
            dock.detect_button.click()
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][0].detection_threshold, 4.5)
            self.assertEqual(requests[0][1], 2.25)
            self.assertTrue(requests[0][2])
        finally:
            dock.deleteLater()

    def test_result_table_updates_positions_and_selection(self) -> None:
        dock = MovingTargetDock()
        selected: list[int] = []
        dock.target_selected.connect(selected.append)
        try:
            dock.set_input_context(5, (64, 64), None)
            dock.set_result(_result(), current_frame=2)
            self.assertEqual(dock.result_table.rowCount(), 1)
            self.assertEqual(dock.result_table.item(0, 2).text(), "14.00")
            self.assertEqual(dock.result_table.item(0, 3).text(), "21.00")
            self.assertTrue(dock.export_button.isEnabled())
            dock.result_table.selectRow(0)
            self.assertEqual(selected, [0])
            dock.set_busy(True)
            self.assertFalse(dock.detect_button.isEnabled())
            self.assertTrue(dock.cancel_button.isEnabled())
        finally:
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
