from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.contracts import TableRowViewModel, TableViewState
from astroview.app.source_table import SourceTableDock
from astroview.core.source_catalog import SourceCatalog, SourceRecord


class TestSourceTableDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_filter_text_reduces_visible_rows_and_preserves_source_indices(self) -> None:
        dock = SourceTableDock()
        clicked: list[int] = []
        dock.source_clicked.connect(clicked.append)
        try:
            rows = [
                TableRowViewModel(row_index=0, values={"ID": 1, "Flux": 10.0}),
                TableRowViewModel(row_index=1, values={"ID": 2, "Flux": 20.0}),
            ]
            dock.set_view_state(TableViewState(has_catalog=True, row_count=2))
            dock.set_row_view_models(rows)
            dock.set_filter_text("20.0")
            self._app.processEvents()

            self.assertEqual(len(dock.filtered_rows), 1)
            self.assertEqual(dock.table_widget.rowCount(), 1)
            dock.table_widget.selectRow(0)
            self._app.processEvents()

            self.assertEqual(clicked, [1])
            self.assertEqual(dock.summary_label.text(), "Showing 1 / 2 sources")
        finally:
            dock.deleteLater()

    def test_sorting_keeps_selection_signal_mapped_to_original_row_index(self) -> None:
        dock = SourceTableDock()
        clicked: list[int] = []
        dock.source_clicked.connect(clicked.append)
        try:
            rows = [
                TableRowViewModel(row_index=0, values={"ID": 1, "Flux": 10.0}),
                TableRowViewModel(row_index=1, values={"ID": 2, "Flux": 50.0}),
            ]
            dock.set_view_state(TableViewState(has_catalog=True, row_count=2))
            dock.set_row_view_models(rows)
            flux_column = next(i for i, column in enumerate(dock.columns) if column.key == "Flux")
            dock.table_widget.sortItems(flux_column, Qt.SortOrder.DescendingOrder)
            self._app.processEvents()

            dock.table_widget.selectRow(0)
            self._app.processEvents()

            self.assertEqual(clicked, [1])
        finally:
            dock.deleteLater()

    def test_selected_source_shows_detail_fields_from_catalog(self) -> None:
        dock = SourceTableDock()
        try:
            dock.populate(
                SourceCatalog(
                    records=[
                        SourceRecord(
                            source_id=7,
                            x=12.5,
                            y=34.5,
                            ra="123.456",
                            dec="-45.678",
                            flux=99.1,
                            peak=12.3,
                            snr=8.7,
                            npix=15,
                            background_rms=0.23,
                            a=2.1,
                            b=1.8,
                            theta=0.5,
                            flag=4,
                        )
                    ]
                )
            )
            dock.set_view_state(TableViewState(has_catalog=True, row_count=1))
            dock.set_row_view_models([TableRowViewModel(row_index=0, values={"ID": 7, "Flux": 99.1})])
            dock.select_source(0)
            self._app.processEvents()

            rendered = {
                dock.detail_table.item(row, 0).text(): dock.detail_table.item(row, 1).text()
                for row in range(dock.detail_table.rowCount())
            }
            self.assertEqual(rendered["ID"], "7")
            self.assertEqual(rendered["X"], "12.5")
            self.assertEqual(rendered["Y"], "34.5")
            self.assertEqual(rendered["RA"], "123.456")
            self.assertEqual(rendered["SNR"], "8.7")
            self.assertEqual(rendered["NPix"], "15")
        finally:
            dock.deleteLater()

    def test_set_cutout_image_updates_preview_pixmap(self) -> None:
        dock = SourceTableDock()
        try:
            image = QImage(12, 10, QImage.Format.Format_Grayscale8)
            image.fill(128)

            dock.set_cutout_image(image)

            self.assertIsNotNone(dock.cutout_view.pixmap())
            self.assertEqual(dock.cutout_view.text(), "")
        finally:
            dock.deleteLater()

    def test_cutout_mode_selector_emits_selected_mode(self) -> None:
        dock = SourceTableDock()
        changed: list[str] = []
        dock.cutout_mode_changed.connect(changed.append)
        try:
            dock.cutout_mode_selector.setCurrentText(SourceTableDock.CUTOUT_MODE_CONNECTED_REGION)
            self._app.processEvents()

            self.assertEqual(dock.current_cutout_mode(), SourceTableDock.CUTOUT_MODE_CONNECTED_REGION)
            self.assertEqual(changed[-1], SourceTableDock.CUTOUT_MODE_CONNECTED_REGION)
        finally:
            dock.deleteLater()

    def test_field_filter_limits_results_to_matching_column(self) -> None:
        dock = SourceTableDock()
        try:
            rows = [
                TableRowViewModel(row_index=0, values={"ID": 1, "Flux": 10.0, "SNR": 5.0}),
                TableRowViewModel(row_index=1, values={"ID": 2, "Flux": 20.0, "SNR": 15.0}),
            ]
            dock.set_view_state(TableViewState(has_catalog=True, row_count=2))
            dock.set_row_view_models(rows)
            dock.set_filter_text("flux:20")
            self._app.processEvents()

            self.assertEqual([row.row_index for row in dock.filtered_rows], [1])
        finally:
            dock.deleteLater()

    def test_status_note_is_appended_to_summary_label(self) -> None:
        dock = SourceTableDock()
        try:
            rows = [
                TableRowViewModel(row_index=0, values={"ID": 1, "Flux": 10.0}),
            ]
            dock.set_view_state(TableViewState(has_catalog=True, row_count=1))
            dock.set_row_view_models(rows)
            dock.set_status_note("Results outdated.")

            self.assertIn("Results outdated.", dock.summary_label.text())
        finally:
            dock.deleteLater()

    def test_inspector_tabs_are_only_visible_when_catalog_exists(self) -> None:
        dock = SourceTableDock()
        try:
            self.assertIs(dock.inspector_tabs.currentWidget(), dock.cutout_panel)
            self.assertEqual(dock.cutout_view.toolTip(), "")
            self.assertIn("Double-click", dock.cutout_hint_label.text())
            self.assertIn("No source selected", dock.cutout_view.text())
            self.assertIn("#60a5fa", dock.cutout_view.styleSheet())
            dock.set_view_state(TableViewState(has_catalog=False, row_count=0))
            self._app.processEvents()
            self.assertFalse(dock.inspector_tabs.isVisible())

            dock.set_view_state(TableViewState(has_catalog=True, row_count=1))
            dock.show()
            self._app.processEvents()
            self.assertTrue(dock.inspector_tabs.isVisible())
            self.assertEqual(dock.inspector_tabs.tabText(0), "Details")
            self.assertEqual(dock.inspector_tabs.tabText(1), "Cutout")
        finally:
            dock.close()
            dock.deleteLater()

    def test_cutout_tab_refreshes_cached_preview_when_activated(self) -> None:
        dock = SourceTableDock()
        try:
            dock.set_view_state(TableViewState(has_catalog=True, row_count=1))
            dock.show()
            dock.inspector_tabs.setCurrentIndex(0)
            self._app.processEvents()

            image = QImage(24, 18, QImage.Format.Format_Grayscale8)
            image.fill(200)
            dock.set_cutout_image(image)
            dock.inspector_tabs.setCurrentIndex(1)
            self._app.processEvents()

            self.assertIsNotNone(dock.cutout_view.pixmap())
            self.assertEqual(dock.inspector_tabs.tabText(1), "Cutout")
        finally:
            dock.close()
            dock.deleteLater()

    def test_clear_cutout_image_formats_custom_placeholder_message(self) -> None:
        dock = SourceTableDock()
        try:
            dock.clear_cutout_image("Connected region unavailable.")

            self.assertIn("Connected region unavailable.", dock.cutout_view.text())
            self.assertIn("#60a5fa", dock.cutout_view.styleSheet())
        finally:
            dock.close()
            dock.deleteLater()

    def test_layout_switches_between_side_and_bottom_dock_modes(self) -> None:
        dock = SourceTableDock()
        try:
            dock.update_layout_for_dock_area(Qt.DockWidgetArea.RightDockWidgetArea)
            self.assertEqual(dock.content_splitter.orientation(), Qt.Orientation.Vertical)

            dock.update_layout_for_dock_area(Qt.DockWidgetArea.BottomDockWidgetArea)
            self.assertEqual(dock.content_splitter.orientation(), Qt.Orientation.Horizontal)
        finally:
            dock.deleteLater()

    def test_clicking_already_selected_row_reemits_source_clicked(self) -> None:
        dock = SourceTableDock()
        clicked: list[int] = []
        dock.source_clicked.connect(clicked.append)
        try:
            rows = [
                TableRowViewModel(row_index=0, values={"ID": 1, "Flux": 10.0}),
                TableRowViewModel(row_index=1, values={"ID": 2, "Flux": 20.0}),
            ]
            dock.set_view_state(TableViewState(has_catalog=True, row_count=2))
            dock.set_row_view_models(rows)
            dock.resize(500, 300)
            dock.show()
            self._app.processEvents()

            dock.table_widget.selectRow(0)
            self._app.processEvents()

            item_rect = dock.table_widget.visualItemRect(dock.table_widget.item(0, 0))
            QTest.mouseClick(
                dock.table_widget.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                item_rect.center(),
            )
            self._app.processEvents()

            self.assertEqual(clicked, [0, 0])
        finally:
            dock.close()
            dock.deleteLater()

    def test_return_key_reemits_current_selection(self) -> None:
        dock = SourceTableDock()
        clicked: list[int] = []
        dock.source_clicked.connect(clicked.append)
        try:
            rows = [
                TableRowViewModel(row_index=0, values={"ID": 1, "Flux": 10.0}),
                TableRowViewModel(row_index=1, values={"ID": 2, "Flux": 20.0}),
            ]
            dock.set_view_state(TableViewState(has_catalog=True, row_count=2))
            dock.set_row_view_models(rows)
            dock.resize(500, 300)
            dock.show()
            dock.table_widget.setFocus()
            self._app.processEvents()

            dock.table_widget.selectRow(1)
            self._app.processEvents()

            QTest.keyClick(dock.table_widget, Qt.Key.Key_Return)
            self._app.processEvents()

            self.assertEqual(clicked, [1, 1])
        finally:
            dock.close()
            dock.deleteLater()

    def test_cutout_double_click_reemits_current_selection(self) -> None:
        dock = SourceTableDock()
        clicked: list[int] = []
        dock.source_clicked.connect(clicked.append)
        try:
            rows = [
                TableRowViewModel(row_index=0, values={"ID": 1, "Flux": 10.0}),
            ]
            dock.set_view_state(TableViewState(has_catalog=True, row_count=1))
            dock.set_row_view_models(rows)
            dock.resize(500, 360)
            dock.show()
            self._app.processEvents()

            dock.table_widget.selectRow(0)
            self._app.processEvents()

            cutout_center = dock.cutout_view.rect().center()
            QTest.mouseDClick(
                dock.cutout_view,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                cutout_center,
            )
            self._app.processEvents()

            self.assertEqual(clicked, [0, 0])
        finally:
            dock.close()
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
