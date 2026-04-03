from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.marker_dock import MarkerDock


class TestMarkerDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_pick_color_emits_color_changed(self) -> None:
        dock = MarkerDock()
        colors: list[str] = []
        dock.color_changed.connect(lambda color: colors.append(color.name()))
        try:
            with patch("astroview.app.marker_dock.QColorDialog.getColor", return_value=QColor("#00ff00")):
                dock._pick_color()

            self.assertEqual(colors, ["#00ff00"])
            self.assertEqual(dock.color().name(), "#00ff00")
        finally:
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
