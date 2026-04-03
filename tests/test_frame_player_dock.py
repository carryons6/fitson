from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.frame_player_dock import FramePlayerDock


class TestFramePlayerDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_set_frame_count_stops_playback_when_frame_count_drops_below_two(self) -> None:
        dock = FramePlayerDock()
        try:
            dock.set_frame_count(3)
            dock.set_current_frame(2)
            dock._start_playback()

            self.assertTrue(dock._playing)

            dock.set_frame_count(1)

            self.assertFalse(dock._playing)
            self.assertEqual(dock.play_btn.text(), "Play")
            self.assertEqual(dock.current_frame(), 0)
        finally:
            dock.deleteLater()

    def test_set_render_state_updates_info_label_for_preview_and_full_render(self) -> None:
        dock = FramePlayerDock()
        try:
            dock.set_frame_count(3)

            dock.set_render_state(True, has_preview=False)
            self.assertEqual(dock.info_label.text(), "3 frame(s) loaded. Waiting for preview...")

            dock.set_render_state(True, has_preview=True)
            self.assertEqual(dock.info_label.text(), "3 frame(s) loaded. Rendering full frame...")

            dock.set_render_state(False, has_preview=True)
            self.assertEqual(dock.info_label.text(), "3 frame(s) loaded.")
        finally:
            dock.deleteLater()

    def test_advance_frame_waits_until_preview_is_available(self) -> None:
        dock = FramePlayerDock()
        try:
            dock.set_frame_count(4)
            dock.set_current_frame(0)
            dock.set_render_state(True, has_preview=False)

            dock._advance_frame()
            self.assertEqual(dock.current_frame(), 0)

            dock.set_render_state(True, has_preview=True)
            dock._advance_frame()
            self.assertEqual(dock.current_frame(), 1)
        finally:
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
