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

    def test_line_width_defaults_to_5(self) -> None:
        dock = MarkerDock()
        try:
            self.assertEqual(dock.line_width(), 5)
        finally:
            dock.deleteLater()

    def test_line_width_spin_supports_up_to_25_and_emits_changes(self) -> None:
        dock = MarkerDock()
        widths: list[int] = []
        dock.line_width_changed.connect(widths.append)
        try:
            dock.line_width_spin.setValue(25)

            self.assertEqual(dock.line_width_spin.maximum(), 25)
            self.assertEqual(dock.line_width(), 25)
            self.assertEqual(widths, [25])
        finally:
            dock.deleteLater()

    def test_apply_reports_invalid_batch_lines(self) -> None:
        dock = MarkerDock()
        updated: list[list[tuple[str, float, float]]] = []
        dock.markers_updated.connect(updated.append)
        try:
            dock.coord_input.setPlainText("10, 20\nbad line\nw 180.0, nope")

            dock._on_apply()

            self.assertEqual(len(updated), 1)
            self.assertEqual(len(updated[0]), 1)
            self.assertEqual(tuple(updated[0][0]), ("pixel", 10.0, 20.0))
            self.assertIn("Skipped 2 invalid line(s)", dock.status_label.text())
            self.assertIn("Line 2", dock.status_label.text())
        finally:
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
