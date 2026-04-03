from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.contracts import TableColumnSpec
from astroview.app.main_window import MainWindow
from astroview.core.fits_data import FITSData
from astroview.core.source_catalog import SourceCatalog, SourceRecord


class _FakeSignal:
    def connect(self, _slot) -> None:
        return None


class _FakeThread:
    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.started = _FakeSignal()
        self.finished = _FakeSignal()

    def isRunning(self) -> bool:
        return False

    def start(self) -> None:
        return None

    def quit(self) -> None:
        return None

    def deleteLater(self) -> None:
        return None


class TestMainWindowLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_open_file_with_explicit_path_starts_background_load(self) -> None:
        window = MainWindow()
        try:
            with patch.object(window, "_start_frame_load") as start_mock:
                window.open_file(path="tests/data/1.FITS", hdu_index=2)

            start_mock.assert_called_once_with(["tests/data/1.FITS"], hdu_index=2, append=False)
        finally:
            window.deleteLater()

    def test_handle_loaded_frame_activates_first_frame(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        try:
            with patch.object(window, "_activate_frame") as activate_mock:
                with patch.object(window, "_sync_frame_player") as sync_mock:
                    window._handle_loaded_frame(FITSData(path="first.fits"), None)

            self.assertEqual(len(window._frames), 1)
            self.assertEqual(len(window._frame_images), 1)
            self.assertEqual(window._frame_dirty, [True])
            activate_mock.assert_called_once_with(0)
            sync_mock.assert_called_once_with()
            window.app_status_bar.set_frame_info.assert_called_once_with(0, 1)
        finally:
            window.deleteLater()

    def test_handle_loaded_frame_preserves_current_frame_during_append(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window._frames = [FITSData(path="existing.fits")]
        window._frame_images = [None]
        window._frame_dirty = [False]
        window._current_frame_index = 0
        try:
            with patch.object(window, "_activate_frame") as activate_mock:
                with patch.object(window, "_sync_frame_player") as sync_mock:
                    window._handle_loaded_frame(FITSData(path="appended.fits"), None)

            self.assertEqual([frame.path for frame in window._frames], ["existing.fits", "appended.fits"])
            self.assertEqual(window._frame_images, [None, None])
            self.assertEqual(window._frame_dirty, [False, True])
            activate_mock.assert_not_called()
            sync_mock.assert_called_once_with()
            window.app_status_bar.set_frame_info.assert_called_once_with(0, 2)
        finally:
            window.deleteLater()

    def test_handle_loaded_frame_uses_preview_image_and_keeps_frame_dirty(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        try:
            with patch.object(window, "_qimage_from_u8", return_value="preview-image") as qimage_mock:
                with patch.object(window, "_activate_frame") as activate_mock:
                    with patch.object(window, "_sync_frame_player") as sync_mock:
                        window._handle_loaded_frame(FITSData(path="first.fits"), preview_image_u8="preview-u8")

            self.assertEqual(window._frame_images, ["preview-image"])
            self.assertEqual(window._frame_dirty, [True])
            qimage_mock.assert_called_once_with("preview-u8")
            activate_mock.assert_called_once_with(0)
            sync_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_activate_frame_schedules_background_render_for_dirty_frame(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="first.fits")]
        window._frame_images = [None]
        window._frame_dirty = [True]
        try:
            with patch.object(window, "_schedule_frame_render") as schedule_mock:
                window._activate_frame(0)

            schedule_mock.assert_called_once_with(0)
        finally:
            window.deleteLater()

    def test_handle_frame_preview_rendered_updates_current_image(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame.fits")]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        window._render_generation = 3
        window._latest_render_request_by_index[0] = 11
        try:
            with patch.object(window, "_qimage_from_u8", return_value="preview-image") as qimage_mock:
                with patch.object(window, "_show_current_frame_image") as show_mock:
                    window._handle_frame_preview_rendered(11, 3, 0, "preview-u8")

            self.assertEqual(window._frame_images, ["preview-image"])
            self.assertEqual(window._frame_dirty, [True])
            qimage_mock.assert_called_once_with("preview-u8")
            show_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_handle_frame_rendered_marks_frame_clean(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame.fits")]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        window._render_generation = 3
        window._latest_render_request_by_index[0] = 12
        try:
            with patch.object(window, "_qimage_from_u8", return_value="final-image") as qimage_mock:
                with patch.object(window, "_show_current_frame_image") as show_mock:
                    window._handle_frame_rendered(12, 3, 0, "full-u8")

            self.assertEqual(window._frame_images, ["final-image"])
            self.assertEqual(window._frame_dirty, [False])
            qimage_mock.assert_called_once_with("full-u8")
            show_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_schedule_frame_render_does_not_cancel_other_active_render_requests(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame-0.fits"), FITSData(path="frame-1.fits")]
        window._frame_images = [None, None]
        window._frame_dirty = [True, True]
        running_thread = Mock()
        running_thread.isRunning.return_value = True
        window._render_threads[8] = running_thread
        window._latest_render_request_by_index[0] = 8
        try:
            with patch.object(window, "_cancel_active_frame_renders") as cancel_mock:
                with patch("astroview.app.main_window.QThread", _FakeThread):
                    with patch("astroview.app.main_window.FrameRenderWorker") as worker_cls:
                        worker_cls.return_value = Mock(
                            moveToThread=Mock(),
                            preview_ready=_FakeSignal(),
                            render_ready=_FakeSignal(),
                            render_error=_FakeSignal(),
                            finished=_FakeSignal(),
                        )
                        window._schedule_frame_render(1)

            cancel_mock.assert_not_called()
            self.assertIn(8, window._render_threads)
            self.assertIn(1, window._latest_render_request_by_index)
        finally:
            window.deleteLater()

    def test_build_table_rows_uses_visible_source_columns(self) -> None:
        window = MainWindow()
        window.source_table_dock = Mock(
            columns=[
                TableColumnSpec(key="ID", title="ID", visible=True),
                TableColumnSpec(key="Flux", title="Flux", visible=True),
                TableColumnSpec(key="SNR", title="SNR", visible=False),
            ]
        )
        catalog = SourceCatalog(
            records=[SourceRecord(source_id=1, x=10.0, y=20.0, flux=3.0, peak=4.0, snr=5.0)]
        )
        try:
            rows = window.build_table_rows(catalog)

            self.assertEqual(rows[0].values, {"ID": 1, "Flux": 3.0})
        finally:
            window.deleteLater()

    def test_show_target_info_fields_dialog_reconfigures_columns(self) -> None:
        window = MainWindow()
        window.source_table_dock = Mock(columns=[TableColumnSpec(key="ID", title="ID")])
        selected_columns = [TableColumnSpec(key="Flux", title="Flux")]
        dialog = Mock()
        dialog.DialogCode = SimpleNamespace(Accepted=1)
        dialog.exec.return_value = 1
        dialog.selected_columns.return_value = selected_columns
        try:
            with patch("astroview.app.main_window.CatalogFieldDialog", return_value=dialog):
                with patch.object(window, "sync_catalog_views") as sync_mock:
                    window._show_target_info_fields_dialog()

            window.source_table_dock.configure_columns.assert_called_once_with(selected_columns)
            sync_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_export_catalog_uses_visible_source_columns(self) -> None:
        window = MainWindow()
        window.current_catalog = MagicMock()
        window.app_status_bar = Mock()
        window.source_table_dock = Mock(
            columns=[
                TableColumnSpec(key="ID", title="ID", visible=True),
                TableColumnSpec(key="Flux", title="Flux", visible=True),
                TableColumnSpec(key="SNR", title="SNR", visible=False),
            ]
        )
        window.current_catalog.__len__.return_value = 1
        try:
            with patch("astroview.app.main_window.QFileDialog.getSaveFileName", return_value=("catalog.csv", "")):
                window.export_catalog()

            window.current_catalog.to_csv.assert_called_once_with("catalog.csv", columns=["ID", "Flux"])
        finally:
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
