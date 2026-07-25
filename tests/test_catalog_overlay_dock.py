from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from astroview.app.catalog_overlay_dock import CatalogOverlayDock
from astroview.core.catalog_service import CatalogSource


class TestCatalogOverlayDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_wcs_state_controls_query_and_grid(self) -> None:
        dock = CatalogOverlayDock()
        try:
            self.assertFalse(dock.query_button.isEnabled())
            dock.set_wcs_state(True, center_ra_deg=180.0, center_dec_deg=45.0, suggested_radius_arcmin=15.0)
            self.assertTrue(dock.query_button.isEnabled())
            self.assertTrue(dock.grid_checkbox.isEnabled())
            self.assertIn("180.000000", dock.center_label.text())
            self.assertEqual(dock.radius_spin.value(), 15.0)
        finally:
            dock.deleteLater()

    def test_query_signal_and_source_table(self) -> None:
        dock = CatalogOverlayDock()
        calls: list[tuple[float, int, float]] = []
        dock.query_requested.connect(lambda radius, limit, faint: calls.append((radius, limit, faint)))
        try:
            dock.set_wcs_state(True, center_ra_deg=1.0, center_dec_deg=2.0)
            dock.radius_spin.setValue(2.5)
            dock.limit_spin.setValue(25)
            dock.faint_limit_spin.setValue(17.0)
            dock.query_button.click()
            self.assertEqual(calls, [(2.5, 25, 17.0)])

            dock.set_sources([CatalogSource("42", 1.25, 2.5, 12.75)])
            self.assertEqual(dock.table.rowCount(), 1)
            self.assertEqual(dock.table.item(0, 0).text(), "42")
            self.assertEqual(dock.table.item(0, 3).text(), "12.750")
            self.assertTrue(dock.clear_button.isEnabled())
        finally:
            dock.deleteLater()

    def test_wcs_refresh_does_not_reenable_query_while_running(self) -> None:
        dock = CatalogOverlayDock()
        try:
            dock.set_wcs_state(True, center_ra_deg=1.0, center_dec_deg=2.0)
            dock.set_query_running(True)
            dock.set_wcs_state(True, center_ra_deg=3.0, center_dec_deg=4.0)
            self.assertFalse(dock.query_button.isEnabled())
            dock.set_query_running(False)
            self.assertTrue(dock.query_button.isEnabled())
        finally:
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
