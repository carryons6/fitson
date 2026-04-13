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

from astroview.app.status_bar import AppStatusBar


class TestAppStatusBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_set_activity_shows_progress_and_cancel_state(self) -> None:
        bar = AppStatusBar()
        try:
            bar.show()
            self._app.processEvents()
            bar.set_activity("Loading FITS 1/3: frame.fits", progress_value=1, progress_max=3, cancellable=True)
            self._app.processEvents()

            self.assertTrue(bar.activity_label.isVisible())
            self.assertEqual(bar.activity_label.text(), "Loading FITS 1/3: frame.fits")
            self.assertTrue(bar.activity_progress.isVisible())
            self.assertEqual(bar.activity_progress.maximum(), 3)
            self.assertEqual(bar.activity_progress.value(), 1)
            self.assertTrue(bar.activity_cancel_btn.isVisible())
        finally:
            bar.close()
            bar.deleteLater()

    def test_show_error_indicator_stores_latest_error(self) -> None:
        bar = AppStatusBar()
        try:
            bar.show()
            self._app.processEvents()
            bar.show_error_indicator("Open failed", "broken header")
            self._app.processEvents()

            self.assertEqual(bar.latest_error(), ("Open failed", "broken header"))
            self.assertTrue(bar.error_label.isVisible())
            self.assertTrue(bar.error_button.isVisible())

            bar.clear_error_indicator()

            self.assertEqual(bar.latest_error(), ("", ""))
            self.assertFalse(bar.error_label.isVisible())
            self.assertFalse(bar.error_button.isVisible())
        finally:
            bar.close()
            bar.deleteLater()


if __name__ == "__main__":
    unittest.main()
