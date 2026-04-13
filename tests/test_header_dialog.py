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

from astroview.app.header_dialog import HeaderDialog


class TestHeaderDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_case_sensitive_toggle_changes_match_count(self) -> None:
        dialog = HeaderDialog()
        try:
            dialog.set_header_text("OBJECT = M31\nobject = lower")
            dialog.set_filter_text("OBJECT")
            dialog.apply_filter()
            self.assertEqual(dialog.filter_state.match_count, 2)

            dialog.set_case_sensitive(True)
            dialog.apply_filter()

            self.assertEqual(dialog.filter_state.match_count, 1)
            self.assertTrue(dialog.case_sensitive_checkbox.isChecked())
        finally:
            dialog.deleteLater()

    def test_zero_match_filter_updates_result_label(self) -> None:
        dialog = HeaderDialog()
        try:
            dialog.set_header_text("OBJECT = M31\nFILTER = g")
            dialog.set_filter_text("EXPTIME")
            dialog.apply_filter()

            self.assertEqual(dialog.filter_state.match_count, 0)
            self.assertIn("No matches", dialog.result_label.text())
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
