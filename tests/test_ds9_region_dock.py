from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.ds9_region_dock import DS9RegionDock
from astroview.core.ds9_regions import (
    DS9Attribute,
    DS9Region,
    DS9RegionDocument,
    DS9RegionError,
    DS9RegionLimitError,
    DS9RegionLimits,
    parse_ds9_regions,
    read_ds9_region_file,
)


class TestDS9RegionDock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_document_preview_uses_effective_attributes_and_emits_selection(self) -> None:
        dock = DS9RegionDock()
        document_events: list[DS9RegionDocument] = []
        selected: list[int] = []
        visibility: list[bool] = []
        dock.document_changed.connect(document_events.append)
        dock.region_selected.connect(selected.append)
        dock.overlay_visibility_changed.connect(visibility.append)
        document = DS9RegionDocument(
            global_attributes=(
                DS9Attribute("color", "green"),
                DS9Attribute("text", "global label"),
            ),
            regions=(
                DS9Region("image", "circle", (10.0, 20.0, 3.0)),
                DS9Region(
                    "fk5",
                    "point",
                    (180.0, 45.0),
                    include=False,
                    attributes=(
                        DS9Attribute("color", "#ff0000"),
                        DS9Attribute("label", "local label"),
                    ),
                ),
            ),
        )
        try:
            dock.set_document(document, source_path="sample.reg")

            self.assertEqual(document_events, [document])
            self.assertEqual(dock.document(), document)
            self.assertEqual(dock.source_path(), Path("sample.reg"))
            self.assertEqual(dock.table.rowCount(), 2)
            self.assertEqual(dock.table.item(0, 4).text(), "global label")
            self.assertEqual(dock.table.item(0, 5).text(), "green")
            self.assertEqual(dock.table.item(1, 3).text(), "Exclude")
            self.assertEqual(dock.table.item(1, 4).text(), "local label")
            self.assertEqual(dock.table.item(1, 5).text(), "#ff0000")
            self.assertTrue(dock.export_button.isEnabled())
            self.assertTrue(dock.clear_button.isEnabled())

            dock.table.setCurrentCell(1, 0)
            self.assertEqual(selected[-1], 1)
            dock.set_overlay_visible(False)
            self.assertEqual(visibility, [False])
        finally:
            dock.deleteLater()

    def test_file_import_export_round_trip_and_clear(self) -> None:
        dock = DS9RegionDock()
        loaded_paths: list[str] = []
        saved_paths: list[str] = []
        documents: list[DS9RegionDocument] = []
        dock.file_loaded.connect(loaded_paths.append)
        dock.file_saved.connect(saved_paths.append)
        dock.document_changed.connect(documents.append)
        try:
            with TemporaryDirectory() as directory:
                source = Path(directory) / "source.reg"
                target = Path(directory) / "target.reg"
                source.write_text(
                    "image\ncircle(1,2,3) # text={target}\n",
                    encoding="utf-8",
                )

                imported = dock.load_file(source, strict=True)
                self.assertIn("Imported 1 region(s)", dock.status_label.text())
                dock.save_file(target)
                exported = read_ds9_region_file(target, strict=True)

                self.assertEqual(exported.regions, imported.regions)
                self.assertEqual(loaded_paths, [str(source)])
                self.assertEqual(saved_paths, [str(target)])
                self.assertIn("Exported 1 region(s)", dock.status_label.text())

                dock.clear_button.click()
                self.assertEqual(dock.document(), DS9RegionDocument())
                self.assertEqual(documents[-1], DS9RegionDocument())
                self.assertFalse(dock.export_button.isEnabled())
                self.assertEqual(dock.table.rowCount(), 0)
        finally:
            dock.deleteLater()

    def test_failed_import_preserves_prior_document_and_reports_non_modally(self) -> None:
        dock = DS9RegionDock()
        prior = DS9RegionDocument(
            regions=(DS9Region("physical", "point", (3.0, 4.0)),),
        )
        failures: list[tuple[str, str]] = []
        dock.operation_failed.connect(lambda operation, message: failures.append((operation, message)))
        try:
            dock.set_document(prior)
            with TemporaryDirectory() as directory:
                invalid = Path(directory) / "invalid.reg"
                invalid.write_bytes(b"\xff\xfe\xfa")
                with self.assertRaises(DS9RegionError):
                    dock.load_file(invalid)

            self.assertEqual(dock.document(), prior)
            self.assertEqual(failures[0][0], "import")
            self.assertIn("failed", dock.status_label.text().lower())
            self.assertLessEqual(len(failures[0][1]), 512)
        finally:
            dock.deleteLater()

    def test_table_and_programmatic_iterables_are_bounded(self) -> None:
        limits = DS9RegionLimits(max_regions=3)
        dock = DS9RegionDock(limits=limits, max_table_rows=2)
        regions = tuple(
            DS9Region("image", "point", (float(index), 1.0))
            for index in range(3)
        )
        try:
            dock.set_document(DS9RegionDocument(regions=regions))
            self.assertEqual(dock.table.rowCount(), 2)
            self.assertIn("showing the first 2", dock.summary_label.text())

            def endless_regions():
                while True:
                    yield regions[0]

            with self.assertRaises(DS9RegionLimitError):
                dock.set_document(DS9RegionDocument(regions=endless_regions()))
        finally:
            dock.deleteLater()

    def test_partial_import_exposes_only_valid_supported_records(self) -> None:
        dock = DS9RegionDock()
        try:
            document = parse_ds9_regions(
                "galactic\npoint(1,2)\nimage\nbox(5,6,7,8) # command={ignored}\n"
            )
            dock.set_document(document)

            self.assertEqual(dock.table.rowCount(), 1)
            self.assertEqual(dock.table.item(0, 1).text(), "image")
            self.assertEqual(dock.table.item(0, 2).text(), "box")
            self.assertEqual(dock.document().regions, document.regions)
            self.assertGreaterEqual(len(dock.document().diagnostics), 3)
        finally:
            dock.deleteLater()

    def test_diagnostics_only_import_can_be_cleared(self) -> None:
        dock = DS9RegionDock()
        try:
            document = parse_ds9_regions("image\ncircle(1,2)\n")
            dock.set_document(document, source_path="invalid.reg")

            self.assertEqual(dock.table.rowCount(), 0)
            self.assertTrue(dock.clear_button.isEnabled())
            dock.clear_button.click()
            self.assertEqual(dock.document(), DS9RegionDocument())
            self.assertIsNone(dock.source_path())
            self.assertFalse(dock.clear_button.isEnabled())
        finally:
            dock.deleteLater()


if __name__ == "__main__":
    unittest.main()
