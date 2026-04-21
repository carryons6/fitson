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

from astroview.app.catalog_field_dialog import CatalogFieldDialog
from astroview.app.contracts import TableColumnSpec
from astroview.app.i18n import install_translator


class TestCatalogFieldDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        install_translator(self._app, "en")

    def test_selected_columns_preserve_order_and_visibility(self) -> None:
        dialog = CatalogFieldDialog(
            [
                TableColumnSpec(key="ID", title="ID", visible=True),
                TableColumnSpec(key="Flux", title="Flux", visible=False),
            ]
        )
        try:
            selected = dialog.selected_columns()

            self.assertEqual([column.key for column in selected], ["ID", "Flux"])
            self.assertEqual([column.visible for column in selected], [True, False])
        finally:
            dialog.deleteLater()

    def test_accept_requires_at_least_one_visible_field(self) -> None:
        dialog = CatalogFieldDialog([TableColumnSpec(key="ID", title="ID", visible=True)])
        try:
            dialog._checkboxes["ID"].setChecked(False)

            dialog._accept_if_valid()

            self.assertEqual(dialog.result(), 0)
            self.assertEqual(dialog.validation_label.text(), "Select at least one field.")
        finally:
            dialog.deleteLater()

    def test_missing_translation_falls_back_to_source_field_title(self) -> None:
        install_translator(self._app, "zh_CN")
        dialog = CatalogFieldDialog(
            [
                TableColumnSpec(key="ID", title="ID", visible=True),
                TableColumnSpec(key="Flux", title="Flux", visible=True),
            ]
        )
        try:
            self.assertEqual(dialog._checkboxes["ID"].text(), "ID")
            self.assertEqual(dialog._checkboxes["Flux"].text(), "Flux")
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
