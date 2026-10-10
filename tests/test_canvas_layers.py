from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from astroview.app.canvas import ImageCanvas
from astroview.core.contracts import ROISelection
from astroview.core.source_catalog import SourceCatalog, SourceRecord


class TestCanvasLayers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_layers_clear_independently_and_keep_selection_styles(self):
        canvas = ImageCanvas()
        try:
            catalog = SourceCatalog(records=[SourceRecord(source_id=1, x=30, y=40, a=2, b=3)])
            canvas.draw_sources(catalog)
            canvas.set_catalog_sources([SimpleNamespace(source_id='42', g_mag=12)], [(30, 40)])
            canvas.set_region_overlays([{'index': 2, 'points': [(20, 20), (40, 40)], 'label': 'R'}])
            canvas.set_measurement_roi(ROISelection(10, 11, 20, 30))
            canvas.set_aperture_overlay(30, 40, (2, 4, 6))
            canvas.set_markers([(60, 60)])
            canvas.set_moving_target_overlays([{'x': 70, 'y': 70}])
            expected_scene = canvas._scene

            canvas.highlight_source(0)
            canvas.set_source_overlay_style(QColor('blue'), 3)
            self.assertEqual(canvas._source_items[0].pen().color(), QColor(255, 255, 0))
            canvas.highlight_catalog_source(0)
            self.assertEqual(canvas._catalog_items[0].pen().width(), 2)
            canvas.highlight_region(2)
            self.assertEqual(canvas._region_path_items[0].pen().color(), QColor(255, 230, 80))

            source_item = canvas._source_items[0]
            region_item = canvas._region_path_items[0]
            canvas.clear_catalog_sources()
            self.assertEqual(canvas._catalog_items, [])
            self.assertIs(source_item.scene(), expected_scene)
            self.assertIs(region_item.scene(), expected_scene)
            self.assertIs(canvas._measurement_roi_item.scene(), expected_scene)

            canvas.clear_measurement_roi()
            self.assertIsNone(canvas._measurement_roi_item)
            self.assertEqual(len(canvas._aperture_items), 3)
            canvas.clear_region_overlays()
            self.assertEqual(canvas._region_path_items, [])
            self.assertEqual(canvas._region_label_items, [])
            self.assertEqual(canvas._region_items_by_index, {})
            self.assertIsNone(region_item.scene())
            self.assertIs(canvas.current_catalog, catalog)

            canvas.clear_sources()
            canvas.clear_sources()
            self.assertIsNone(canvas.current_catalog)
            self.assertIsNone(source_item.scene())
            self.assertEqual(len(canvas._marker_items), 1)
            self.assertEqual(len(canvas._moving_target_items), 2)
            self.assertEqual(len(canvas._aperture_items), 3)
        finally:
            canvas.close()
            canvas.deleteLater()


if __name__ == '__main__':
    unittest.main()
