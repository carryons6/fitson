from __future__ import annotations

import gzip
import os
import threading
import time
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QByteArray, QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview import __version__
from astroview.app.contracts import HeaderPayload, HeaderViewState, TableColumnSpec
from astroview.app.main_window import (
    MainWindow,
    _FrameBkgThreadFinishRelay,
    _FrameRenderThreadFinishRelay,
    _LoadSignalRelay,
    _UpdateCheckSignalRelay,
)
from astroview.app.update_check_worker import UpdateCheckResult
from astroview.core.contracts import ROISelection
from astroview.core.sep_service import SEPParameters
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


class _ThreadLoadEmitter(QObject):
    file_loaded = Signal(object, object)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        self.file_loaded.emit(FITSData(path="threaded.fits"), None)
        self.finished.emit()


class _ThreadUpdateEmitter(QObject):
    result_ready = Signal(object)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        self.result_ready.emit(
            UpdateCheckResult(status="up_to_date", current_version=__version__)
        )
        self.finished.emit()


class _ThreadFinishEmitter(QObject):
    finished = Signal()

    @Slot()
    def run(self) -> None:
        self.finished.emit()


class TestMainWindowLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _grayscale_image(values: list[list[int]]) -> QImage:
        array = np.asarray(values, dtype=np.uint8)
        if array.ndim != 2:
            raise ValueError("grayscale test image must be 2D")
        image = QImage(
            array.data,
            int(array.shape[1]),
            int(array.shape[0]),
            int(array.strides[0]),
            QImage.Format.Format_Grayscale8,
        )
        return image.copy()

    @staticmethod
    def _assert_settings_write(settings_mock: Mock, key: str, value: object) -> None:
        writes = [call.args for call in settings_mock.setValue.call_args_list]
        assert (key, value) in writes, f"Missing settings write {(key, value)!r}; got {writes!r}"

    @classmethod
    def _wait_until(cls, predicate, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cls._app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Timed out while waiting for Qt background work to finish.")

    def test_open_file_with_explicit_path_starts_background_load(self) -> None:
        window = MainWindow()
        try:
            with patch.object(window, "_start_frame_load") as start_mock:
                window.open_file(path="tests/data/1.FITS", hdu_index=2)

            start_mock.assert_called_once_with(["tests/data/1.FITS"], hdu_index=2, append=False)
        finally:
            window.deleteLater()

    def test_open_file_resets_render_controls_to_linear_and_zscale(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window.fits_service.set_stretch("Asinh")
        window.fits_service.set_interval("99%")
        window.fits_service.set_manual_interval_limits(1.0, 2.0)
        try:
            with patch.object(window, "_start_frame_load"):
                window.open_file(path="tests/data/1.FITS")

            self.assertEqual(window.fits_service.current_stretch, "Linear")
            self.assertEqual(window.fits_service.current_interval, "ZScale")
            self.assertIsNone(window.fits_service.manual_interval_limits)
            self._assert_settings_write(window._settings, "render/stretch", "Linear")
            self._assert_settings_write(window._settings, "render/interval", "ZScale")
        finally:
            window.deleteLater()

    def test_apply_startup_request_opens_initial_file_only_once(self) -> None:
        window = MainWindow(initial_path="tests/data/1.FITS", initial_hdu=2)
        try:
            with patch.object(window, "open_file_from_request") as open_mock:
                window.apply_startup_request()
                window.apply_startup_request()

            open_mock.assert_called_once()
            request = open_mock.call_args.args[0]
            self.assertEqual(request.path, "tests/data/1.FITS")
            self.assertEqual(request.hdu_index, 2)
        finally:
            window.deleteLater()

    def test_schedule_startup_request_defers_when_initial_path_is_present(self) -> None:
        window = MainWindow(initial_path="tests/data/1.FITS")
        try:
            with patch("astroview.app.main_window.QTimer.singleShot") as single_shot_mock:
                window.schedule_startup_request()

            single_shot_mock.assert_called_once_with(0, window.apply_startup_request)
        finally:
            window.deleteLater()

    def test_open_file_with_explicit_path_remembers_parent_directory(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        try:
            with patch.object(window, "_start_frame_load"):
                window.open_file(path="tests/data/1.FITS")

            self._assert_settings_write(window._settings, "paths/last_open_dir", "tests\\data")
        finally:
            window.deleteLater()

    def test_open_file_dialog_uses_and_updates_last_open_directory(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window._settings.value.return_value = "D:\\fits"
        try:
            with patch.object(window, "_start_frame_load") as start_mock:
                with patch(
                    "astroview.app.main_window.QFileDialog.getOpenFileNames",
                    return_value=(["D:\\fits\\new\\image.fits"], ""),
                ) as dialog_mock:
                    window.open_file()

            dialog_mock.assert_called_once_with(
                window,
                "Open FITS File(s)",
                "D:\\fits",
                "FITS Files (*.fits *.fit *.fts);;All Files (*)",
            )
            self._assert_settings_write(window._settings, "paths/last_open_dir", "D:\\fits\\new")
            start_mock.assert_called_once_with(["D:\\fits\\new\\image.fits"], hdu_index=None, append=False)
        finally:
            window.deleteLater()

    def test_append_frames_dialog_uses_and_updates_last_open_directory(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window._settings.value.return_value = "D:\\fits"
        try:
            with patch.object(window, "_start_frame_load") as start_mock:
                with patch(
                    "astroview.app.main_window.QFileDialog.getOpenFileNames",
                    return_value=(["D:\\fits\\append\\frame2.fits"], ""),
                ) as dialog_mock:
                    window._append_frames()

            dialog_mock.assert_called_once_with(
                window,
                "Append FITS Frame(s)",
                "D:\\fits",
                "FITS Files (*.fits *.fit *.fts);;All Files (*)",
            )
            self._assert_settings_write(window._settings, "paths/last_open_dir", "D:\\fits\\append")
            start_mock.assert_called_once_with(["D:\\fits\\append\\frame2.fits"], hdu_index=None, append=True)
        finally:
            window.deleteLater()

    def test_open_file_remembers_recent_paths(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window._settings.value.return_value = []
        try:
            with patch.object(window, "_start_frame_load"):
                window.open_file(path="D:\\fits\\image.fits")

            self._assert_settings_write(window._settings, "paths/recent_files", ["D:\\fits\\image.fits"])
        finally:
            window.deleteLater()

    def test_handle_dropped_paths_opens_only_supported_fits_files(self) -> None:
        window = MainWindow()
        try:
            with patch.object(window, "_open_paths") as open_mock:
                window._handle_dropped_paths([
                    "D:\\fits\\frame1.fits",
                    "D:\\fits\\notes.txt",
                    "D:\\fits\\frame2.FIT",
                ])

            open_mock.assert_called_once_with(
                ["D:\\fits\\frame1.fits", "D:\\fits\\frame2.FIT"],
                append=False,
            )
        finally:
            window.deleteLater()

    def test_handle_dropped_paths_reports_error_for_unsupported_files(self) -> None:
        window = MainWindow()
        try:
            with patch.object(window, "show_error") as error_mock:
                window._handle_dropped_paths(["D:\\fits\\notes.txt"])

            error_mock.assert_called_once_with(
                "Open failed",
                "Drop one or more FITS files (.fits, .fit, .fts).",
            )
        finally:
            window.deleteLater()

    def test_restore_render_preferences_uses_persisted_values(self) -> None:
        window = MainWindow()
        window._settings = Mock()

        def value_side_effect(key, default=None, type=None):
            if key == "render/stretch":
                return "Asinh"
            if key == "render/interval":
                return "99%"
            if key == "render/preview_profile":
                return "Detailed"
            return default

        window._settings.value.side_effect = value_side_effect
        try:
            window._restore_render_preferences()

            self.assertEqual(window.fits_service.current_stretch, "Asinh")
            self.assertEqual(window.fits_service.current_interval, "99%")
            self.assertEqual(window._preview_profile_name, "Detailed")
        finally:
            window.deleteLater()

    def test_restore_workspace_state_applies_marker_preferences_and_window_state(self) -> None:
        window = MainWindow()
        window.create_actions()
        window.build_ui()
        window._settings = Mock()

        geometry = QByteArray(b"geometry")
        state = QByteArray(b"state")

        def value_side_effect(key, default=None, type=None):
            values = {
                "markers/radius": 42.0,
                "markers/line_width": 7,
                "markers/color": "#00ff00",
                "window/geometry": geometry,
                "window/state": state,
                "window/layout_version": MainWindow.WORKSPACE_LAYOUT_VERSION,
            }
            return values.get(key, default)

        window._settings.value.side_effect = value_side_effect
        try:
            with patch.object(window, "_can_restore_saved_geometry", return_value=True):
                with patch.object(window, "restoreGeometry") as restore_geometry_mock:
                    with patch.object(window, "restoreState") as restore_state_mock:
                        window._restore_workspace_state()

            self.assertEqual(window.marker_dock.radius(), 42.0)
            self.assertEqual(window.marker_dock.line_width(), 7)
            self.assertEqual(window.marker_dock.color().name(), "#00ff00")
            restore_geometry_mock.assert_called_once_with(geometry)
            restore_state_mock.assert_called_once_with(state)
        finally:
            window.deleteLater()

    def test_restore_workspace_state_uses_default_layout_when_saved_version_is_stale(self) -> None:
        window = MainWindow()
        window.create_actions()
        window.build_ui()
        window._settings = Mock()

        geometry = QByteArray(b"geometry")
        state = QByteArray(b"state")

        def value_side_effect(key, default=None, type=None):
            values = {
                "window/geometry": geometry,
                "window/state": state,
                "window/layout_version": MainWindow.WORKSPACE_LAYOUT_VERSION - 1,
            }
            return values.get(key, default)

        window._settings.value.side_effect = value_side_effect
        try:
            with patch.object(window, "_can_restore_saved_geometry", return_value=True):
                with patch.object(window, "restoreGeometry") as restore_geometry_mock:
                    with patch.object(window, "restoreState") as restore_state_mock:
                        with patch.object(window, "_apply_default_workspace_layout") as default_layout_mock:
                            window._restore_workspace_state()

            restore_geometry_mock.assert_called_once_with(geometry)
            restore_state_mock.assert_not_called()
            default_layout_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_build_ui_tabs_source_table_sep_and_markers_on_right(self) -> None:
        window = MainWindow()
        window.create_actions()
        try:
            window.build_ui()
            window.show()
            window.source_table_dock.show()
            window.sep_panel_dock.show()
            window.frame_player_dock.show()
            window.marker_dock.show()
            window.source_table_dock.raise_()
            self._app.processEvents()

            self.assertEqual(
                window.dockWidgetArea(window.source_table_dock),
                Qt.DockWidgetArea.RightDockWidgetArea,
            )
            self.assertEqual(
                window.dockWidgetArea(window.frame_player_dock),
                Qt.DockWidgetArea.BottomDockWidgetArea,
            )
            self.assertEqual(
                window.dockWidgetArea(window.sep_panel_dock),
                Qt.DockWidgetArea.RightDockWidgetArea,
            )
            self.assertEqual(
                window.dockWidgetArea(window.marker_dock),
                Qt.DockWidgetArea.RightDockWidgetArea,
            )
            self.assertEqual(
                window.dockWidgetArea(window.histogram_dock),
                Qt.DockWidgetArea.LeftDockWidgetArea,
            )
            self.assertIn(window.sep_panel_dock, window.tabifiedDockWidgets(window.source_table_dock))
            self.assertIn(window.marker_dock, window.tabifiedDockWidgets(window.source_table_dock))
            self.assertEqual(len(window.tabifiedDockWidgets(window.frame_player_dock)), 0)
            self.assertEqual(
                window.source_table_dock.content_splitter.orientation(),
                Qt.Orientation.Vertical,
            )
            self.assertIs(
                window.source_table_dock.inspector_tabs.currentWidget(),
                window.source_table_dock.cutout_panel,
            )
        finally:
            window.close()
            window.deleteLater()

    def test_restore_workspace_state_skips_geometry_when_screen_metadata_is_missing(self) -> None:
        window = MainWindow()
        window.create_actions()
        window.build_ui()
        window._settings = Mock()

        geometry = QByteArray(b"geometry")

        def value_side_effect(key, default=None, type=None):
            values = {
                "window/geometry": geometry,
                "window/state": QByteArray(),
                "window/layout_version": MainWindow.WORKSPACE_LAYOUT_VERSION,
                "window/screen_name": "",
                "window/screen_available_width": 0,
                "window/screen_available_height": 0,
            }
            return values.get(key, default)

        window._settings.value.side_effect = value_side_effect
        try:
            with patch.object(window, "restoreGeometry") as restore_geometry_mock:
                window._restore_workspace_state()

            restore_geometry_mock.assert_not_called()
        finally:
            window.deleteLater()

    def test_handle_stretch_changed_persists_render_preferences(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        try:
            window._handle_stretch_changed("Asinh")

            self.assertEqual(window.fits_service.current_stretch, "Asinh")
            self._assert_settings_write(window._settings, "render/stretch", "Asinh")
            self._assert_settings_write(window._settings, "render/interval", "ZScale")
            self._assert_settings_write(window._settings, "render/preview_profile", "Balanced")
        finally:
            window.deleteLater()

    def test_handle_interval_changed_persists_render_preferences(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        try:
            window._handle_interval_changed("99%")

            self.assertEqual(window.fits_service.current_interval, "99%")
            self._assert_settings_write(window._settings, "render/stretch", "Linear")
            self._assert_settings_write(window._settings, "render/interval", "99%")
            self._assert_settings_write(window._settings, "render/preview_profile", "Balanced")
        finally:
            window.deleteLater()

    def test_handle_preview_profile_changed_persists_selection_and_rerenders(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        try:
            with patch.object(window, "_rerender_all_frames") as rerender_mock:
                with patch.object(window, "_show_current_frame_image") as show_mock:
                    window._handle_preview_profile_changed("Detailed")

            self.assertEqual(window._preview_profile_name, "Detailed")
            self._assert_settings_write(window._settings, "render/preview_profile", "Detailed")
            rerender_mock.assert_called_once_with()
            show_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_orient_qimage_matches_orient_point_for_all_supported_orientations(self) -> None:
        window = MainWindow()
        image = QImage(3, 2, QImage.Format.Format_RGB32)
        values = [
            [10, 20, 30],
            [40, 50, 60],
        ]
        try:
            for y, row in enumerate(values):
                for x, value in enumerate(row):
                    image.setPixelColor(x, y, QColor(value, value, value))

            for _label, orientation in window._ORIENTATIONS:
                window._orientation = orientation
                oriented = window._orient_qimage(image)
                expected_width = image.height() if orientation[2] else image.width()
                expected_height = image.width() if orientation[2] else image.height()
                self.assertEqual(oriented.width(), expected_width)
                self.assertEqual(oriented.height(), expected_height)
                for y, row in enumerate(values):
                    for x, value in enumerate(row):
                        dx, dy = window._orient_point(x, y, image.width(), image.height())
                        self.assertEqual(oriented.pixelColor(int(dx), int(dy)).red(), value)
        finally:
            window.deleteLater()

    def test_repeated_render_control_changes_restart_in_flight_renders(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [window.fits_service.current_data]
        window._frame_images = ["old-image"]
        window._frame_dirty = [False]
        window._current_frame_index = 0
        window._render_generation = 4
        window._render_request_index_by_id = {9: 0}
        window._latest_render_request_by_index = {0: 9}
        try:
            with patch.object(window, "_cancel_active_frame_renders") as cancel_mock:
                with patch.object(window, "_ensure_frame_rendered") as ensure_mock:
                    with patch.object(window, "_show_current_frame_image") as show_mock:
                        window._handle_stretch_changed("Asinh")
                        window._handle_interval_changed("99%")

            self.assertEqual(window._render_generation, 6)
            self.assertEqual(window._frame_dirty, [True])
            self.assertEqual(window._render_request_index_by_id, {})
            self.assertEqual(window._latest_render_request_by_index, {})
            self.assertEqual(cancel_mock.call_count, 2)
            cancel_mock.assert_any_call(wait=False)
            self.assertEqual(ensure_mock.call_count, 2)
            ensure_mock.assert_any_call(0)
            self.assertEqual(show_mock.call_count, 2)
        finally:
            window.deleteLater()

    def test_stale_render_results_are_ignored_after_repeated_render_control_changes(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [window.fits_service.current_data]
        window._frame_images = ["fresh-image"]
        window._frame_dirty = [False]
        window._current_frame_index = 0
        window._render_generation = 10
        window._latest_render_request_by_index = {0: 40}
        try:
            with patch.object(window, "_cancel_active_frame_renders"):
                with patch.object(window, "_ensure_frame_rendered"):
                    with patch.object(window, "_show_current_frame_image"):
                        window._handle_stretch_changed("Asinh")
                        window._handle_interval_changed("99%")

            self.assertEqual(window._render_generation, 12)
            window._latest_render_request_by_index[0] = 41
            window._frame_images[0] = "fresh-image"
            window._frame_dirty[0] = True

            with patch.object(window, "_qimage_from_u8", return_value="stale-preview") as qimage_mock:
                with patch.object(window, "_show_current_frame_image") as show_mock:
                    window._handle_frame_preview_rendered(40, 10, 0, "preview-u8")

            qimage_mock.assert_not_called()
            show_mock.assert_not_called()
            self.assertEqual(window._frame_images[0], "fresh-image")

            with patch.object(window, "_qimage_from_u8", return_value="stale-full") as qimage_mock:
                with patch.object(window, "_show_current_frame_image") as show_mock:
                    window._handle_frame_rendered(40, 10, 0, "full-u8")

            qimage_mock.assert_not_called()
            show_mock.assert_not_called()
            self.assertEqual(window._frame_images[0], "fresh-image")
            self.assertTrue(window._frame_dirty[0])
        finally:
            window.deleteLater()

    def test_persist_marker_preferences_writes_current_values(self) -> None:
        window = MainWindow()
        window.create_actions()
        window.build_ui()
        window._settings = Mock()
        window.marker_dock.set_radius(33.0)
        window.marker_dock.set_line_width(9)
        window.marker_dock.set_color("#112233")
        try:
            window._persist_marker_preferences()

            self._assert_settings_write(window._settings, "markers/radius", 33.0)
            self._assert_settings_write(window._settings, "markers/line_width", 9)
            self._assert_settings_write(window._settings, "markers/color", "#112233")
        finally:
            window.deleteLater()

    def test_close_event_persists_window_state(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        event = Mock()
        try:
            with patch.object(window, "_stop_active_frame_load") as stop_load_mock:
                with patch.object(window, "_cancel_active_frame_renders") as cancel_renders_mock:
                    with patch.object(window, "_cancel_bkg_workers") as cancel_bkg_mock:
                        with patch.object(window, "_cancel_active_sep_extract") as cancel_sep_mock:
                            with patch.object(window, "_stop_update_check") as stop_update_mock:
                                with patch.object(window, "saveGeometry", return_value=QByteArray(b"g")):
                                    with patch.object(window, "saveState", return_value=QByteArray(b"s")):
                                        with patch("PySide6.QtWidgets.QMainWindow.closeEvent") as super_close_mock:
                                            window.closeEvent(event)

            stop_load_mock.assert_called_once_with(wait=False)
            cancel_renders_mock.assert_called_once_with(wait=False)
            cancel_bkg_mock.assert_called_once_with(wait=False)
            cancel_sep_mock.assert_called_once_with(wait=False)
            stop_update_mock.assert_called_once_with(wait=False)
            self._assert_settings_write(window._settings, "window/geometry", QByteArray(b"g"))
            self._assert_settings_write(window._settings, "window/state", QByteArray(b"s"))
            self._assert_settings_write(
                window._settings,
                "window/layout_version",
                MainWindow.WORKSPACE_LAYOUT_VERSION,
            )
            super_close_mock.assert_called_once_with(event)
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

    def test_close_event_defers_destruction_while_a_worker_thread_is_running(self) -> None:
        window = MainWindow()
        event = Mock()
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        window._load_thread = thread
        window._load_worker = worker
        window._active_load_request_id = 1
        try:
            with patch.object(window, "_persist_window_state") as persist_mock:
                with patch("PySide6.QtWidgets.QMainWindow.closeEvent") as super_close_mock:
                    window.closeEvent(event)

            event.ignore.assert_called_once_with()
            persist_mock.assert_not_called()
            super_close_mock.assert_not_called()
            thread.requestInterruption.assert_called_once_with()
            thread.quit.assert_called_once_with()
            thread.terminate.assert_not_called()
            self.assertTrue(window._close_pending)

            thread.isRunning.return_value = False
            with patch.object(window, "close") as close_mock:
                window._retry_pending_close()
            close_mock.assert_called_once_with()
            self.assertFalse(window._close_pending)
        finally:
            window._load_thread = None
            window._load_worker = None
            window._active_load_request_id = None
            window.deleteLater()

    def test_render_thread_cleanup_does_not_spawn_followup_work_while_closing(self) -> None:
        window = MainWindow()
        window._is_closing = True
        window._render_threads[3] = Mock()
        window._render_workers[3] = Mock()
        window._render_request_index_by_id[3] = 0
        try:
            with patch.object(window, "_pump_playback_render_queue") as pump_mock:
                with patch.object(window, "_schedule_next_composite_dirty_frame") as schedule_mock:
                    window._handle_frame_render_thread_finished(3)

            pump_mock.assert_not_called()
            schedule_mock.assert_not_called()
            self.assertNotIn(3, window._render_threads)
        finally:
            window.deleteLater()

    def test_stale_load_callbacks_cannot_mutate_or_clear_a_new_request(self) -> None:
        window = MainWindow()
        old_thread = Mock()
        old_worker = Mock()
        new_thread = Mock()
        new_worker = Mock()
        window._active_load_request_id = 2
        window._load_thread = new_thread
        window._load_worker = new_worker
        try:
            with patch.object(window, "_handle_loaded_frame") as loaded_mock:
                with patch.object(window, "_finish_frame_load") as finish_mock:
                    window._handle_loaded_frame_for_request(
                        1,
                        old_worker,
                        FITSData(path="stale.fits"),
                        None,
                    )
                    window._finish_frame_load_for_request(1, old_worker)
                    window._clear_load_worker_refs(1, old_thread, old_worker)

            loaded_mock.assert_not_called()
            finish_mock.assert_not_called()
            self.assertIs(window._load_thread, new_thread)
            self.assertIs(window._load_worker, new_worker)
            self.assertEqual(window._active_load_request_id, 2)
        finally:
            window._load_thread = None
            window._load_worker = None
            window.deleteLater()

    def test_load_signal_relay_runs_main_window_handler_on_gui_thread(self) -> None:
        window = MainWindow()
        thread = QThread()
        worker = _ThreadLoadEmitter()
        worker.moveToThread(thread)
        relay = _LoadSignalRelay(window, 1, thread, worker)
        window._active_load_request_id = 1
        window._load_thread = thread
        window._load_worker = worker
        window._load_results_enabled = True
        handler_threads: list[QThread] = []
        try:
            thread.started.connect(worker.run)
            worker.file_loaded.connect(relay.handle_loaded)
            worker.finished.connect(worker.deleteLater)
            worker.finished.connect(thread.quit)
            thread.finished.connect(relay.deleteLater)

            with patch.object(
                window,
                "_handle_loaded_frame",
                side_effect=lambda _data, _preview: handler_threads.append(QThread.currentThread()),
            ):
                thread.start()
                self._wait_until(lambda: bool(handler_threads) and not thread.isRunning())

            self.assertIs(handler_threads[0], window.thread())
        finally:
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                thread.wait(3000)
            window._load_thread = None
            window._load_worker = None
            window._active_load_request_id = None
            thread.deleteLater()
            window.deleteLater()

    def test_render_thread_finish_relay_runs_cleanup_on_gui_thread(self) -> None:
        window = MainWindow()
        thread = QThread()
        emitter = _ThreadFinishEmitter()
        emitter.moveToThread(thread)
        relay = _FrameRenderThreadFinishRelay(window, 3, 0)
        cleanup_threads: list[QThread] = []
        try:
            thread.started.connect(emitter.run)
            emitter.finished.connect(thread.quit)
            emitter.finished.connect(emitter.deleteLater)
            thread.finished.connect(relay.handle_thread_finished)
            thread.finished.connect(relay.deleteLater)

            with patch.object(
                window,
                "_handle_frame_render_thread_finished",
                side_effect=lambda *_args: cleanup_threads.append(QThread.currentThread()),
            ):
                thread.start()
                self._wait_until(
                    lambda: bool(cleanup_threads) and not thread.isRunning()
                )

            self.assertIs(cleanup_threads[0], window.thread())
        finally:
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                thread.wait(3000)
            thread.deleteLater()
            window.deleteLater()

    def test_bkg_thread_finish_relay_runs_cleanup_on_gui_thread(self) -> None:
        window = MainWindow()
        thread = QThread()
        emitter = _ThreadFinishEmitter()
        emitter.moveToThread(thread)
        relay = _FrameBkgThreadFinishRelay(window, 0, 4, thread, Mock())
        cleanup_threads: list[QThread] = []
        try:
            thread.started.connect(emitter.run)
            emitter.finished.connect(thread.quit)
            emitter.finished.connect(emitter.deleteLater)
            thread.finished.connect(relay.handle_thread_finished)
            thread.finished.connect(relay.deleteLater)

            with patch.object(
                window,
                "_handle_bkg_thread_finished",
                side_effect=lambda *_args: cleanup_threads.append(QThread.currentThread()),
            ):
                thread.start()
                self._wait_until(
                    lambda: bool(cleanup_threads) and not thread.isRunning()
                )

            self.assertIs(cleanup_threads[0], window.thread())
        finally:
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                thread.wait(3000)
            thread.deleteLater()
            window.deleteLater()

    def test_set_loading_state_updates_status_bar_activity(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        try:
            window._set_loading_state(True, loaded=2, total=5, current_path="D:\\fits\\frame2.fits")

            window.app_status_bar.set_activity.assert_called_once_with(
                "Loading FITS 2/5: frame2.fits",
                progress_value=2,
                progress_max=5,
                cancellable=True,
            )

            window._set_loading_state(False)

            window.app_status_bar.clear_activity.assert_called_once_with()
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

    def test_activate_frame_atomically_clears_previous_sep_catalog_and_pending_launch(self) -> None:
        window = MainWindow()
        first = FITSData(path="first.fits", data=np.zeros((2, 2)))
        second = FITSData(path="second.fits", data=np.ones((2, 2)))
        window._frames = [first, second]
        window._frame_images = [None, None]
        window._frame_dirty = [False, False]
        window._frame_bkg_cache = [None, None]
        window._frame_residual_cache = [None, None]
        window._frame_cached_preview_dim = [0, 0]
        window._current_frame_index = 0
        window.fits_service.current_data = first
        window.current_catalog = SourceCatalog(
            records=[SourceRecord(source_id=1, x=1.0, y=1.0)]
        )
        window.canvas = Mock()
        window.source_table_dock = Mock()
        pending_roi = ROISelection(x0=0, y0=0, width=2, height=2)
        window._sep_pending_launch_roi = window._pending_sep_action(pending_roi)
        window._sep_confirm_pending_roi = window._pending_sep_action(pending_roi)
        try:
            with patch.object(window, "_show_current_frame_image"):
                with patch.object(window, "_refresh_histogram_view"):
                    with patch.object(window, "_persist_session_state"):
                        window._activate_frame(1)

            self.assertIsNone(window.current_catalog)
            self.assertIsNone(window._sep_pending_launch_roi)
            self.assertIsNone(window._sep_confirm_pending_roi)
            window.canvas.clear_sources.assert_called_once_with()
            window.source_table_dock.clear_catalog.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_cancelled_sep_estimate_cannot_launch_full_extract_during_thread_cleanup(self) -> None:
        window = MainWindow()
        frame = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [frame]
        window.fits_service.current_data = frame
        window._current_frame_index = 0
        window._active_sep_request_id = 5
        window._active_sep_context_generation = window._sep_context_generation
        window._active_sep_frame_index = 0
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        window._sep_thread = thread
        window._sep_worker = worker
        window._sep_pending_launch_roi = window._pending_sep_action(
            ROISelection(x0=0, y0=0, width=2, height=2)
        )
        try:
            with patch.object(window, "_start_sep_extract_full") as start_mock:
                window._cancel_active_sep_extract(wait=False)
                window._clear_sep_worker_refs(5, thread, worker)

            start_mock.assert_not_called()
            self.assertIsNone(window._sep_pending_launch_roi)
            self.assertIsNone(window._sep_thread)
            worker.cancel.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_cancelled_sep_request_rejects_already_queued_result(self) -> None:
        window = MainWindow()
        frame = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [frame]
        window.fits_service.current_data = frame
        window._current_frame_index = 0
        window._active_sep_request_id = 6
        window._active_sep_context_generation = window._sep_context_generation
        window._active_sep_frame_index = 0
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        window._sep_thread = thread
        window._sep_worker = worker
        catalog = SourceCatalog(records=[SourceRecord(source_id=1, x=1.0, y=1.0)])
        try:
            with patch.object(window, "set_current_catalog") as set_catalog_mock:
                window._cancel_active_sep_extract(wait=False)
                window._handle_sep_extraction_ready(
                    6,
                    ROISelection(x0=0, y0=0, width=2, height=2),
                    catalog,
                )

            set_catalog_mock.assert_not_called()
            self.assertIsNone(window.current_catalog)
            self.assertFalse(window._sep_request_matches_current_context(6))
        finally:
            window._sep_thread = None
            window._sep_worker = None
            window._active_sep_request_id = None
            window.deleteLater()

    def test_sep_result_from_previous_frame_is_ignored_during_fast_switch(self) -> None:
        window = MainWindow()
        first = FITSData(path="first.fits", data=np.zeros((2, 2)))
        second = FITSData(path="second.fits", data=np.ones((2, 2)))
        window._frames = [first, second]
        window._current_frame_index = 1
        window.fits_service.current_data = second
        window._sep_context_generation = 2
        window._active_sep_request_id = 9
        window._active_sep_context_generation = 1
        window._active_sep_frame_index = 0
        catalog = SourceCatalog(records=[SourceRecord(source_id=1, x=1.0, y=1.0)])
        try:
            with patch.object(window, "sync_catalog_views") as sync_mock:
                window._handle_sep_extraction_ready(
                    9,
                    ROISelection(x0=0, y0=0, width=2, height=2),
                    catalog,
                )

            self.assertIsNone(window.current_catalog)
            sync_mock.assert_not_called()
        finally:
            window.deleteLater()

    def test_bkg_result_survives_unrelated_render_generation_change(self) -> None:
        window = MainWindow()
        original = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        background = np.ones((2, 2), dtype=np.float32)
        residual = np.full((2, 2), 2.0, dtype=np.float32)
        window._frames = [original]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._frame_cached_preview_dim = [0]
        window._view_mode = "background"
        window._bkg_generation = 3
        window._render_generation = 99
        try:
            with patch.object(window, "_schedule_frame_render") as schedule_mock:
                window._handle_bkg_ready(0, 3, background, residual)

            np.testing.assert_array_equal(window._frame_bkg_cache[0].data, background)
            np.testing.assert_array_equal(window._frame_residual_cache[0].data, residual)
            schedule_mock.assert_called_once_with(0)
        finally:
            window.deleteLater()

    def test_stale_bkg_completion_redispatches_under_current_generation(self) -> None:
        window = MainWindow()
        frame = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [frame]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._frame_cached_preview_dim = [0]
        window._view_mode = "background"
        window._bkg_generation = 8
        thread = Mock()
        worker = Mock()
        worker.generation = 7
        window._bkg_threads[0] = thread
        window._bkg_workers[0] = worker
        try:
            with patch.object(window, "_ensure_frame_rendered") as ensure_mock:
                window._handle_bkg_thread_finished(0, 7, thread, worker)

            self.assertNotIn(0, window._bkg_threads)
            self.assertNotIn(0, window._bkg_workers)
            ensure_mock.assert_called_once_with(0)
        finally:
            window.deleteLater()

    def test_stale_bkg_completion_redispatches_for_source_cutout_in_original_view(self) -> None:
        window = MainWindow()
        frame = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [frame]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._view_mode = "original"
        window._current_frame_index = 0
        window._bkg_generation = 8
        window.source_table_dock = Mock()
        window.source_table_dock.current_cutout_mode.return_value = "Background"
        thread = Mock()
        worker = Mock()
        worker.generation = 7
        window._bkg_threads[0] = thread
        window._bkg_workers[0] = worker
        try:
            with patch.object(window, "_dispatch_bkg_worker") as dispatch_mock:
                window._handle_bkg_thread_finished(0, 7, thread, worker)

            dispatch_mock.assert_called_once_with(0)
        finally:
            window.deleteLater()

    def test_current_bkg_error_ends_render_feedback_without_retry_loop(self) -> None:
        window = MainWindow()
        frame = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [frame]
        window._frame_dirty = [True]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._view_mode = "background"
        window._current_frame_index = 0
        window._bkg_generation = 4
        thread = Mock()
        worker = Mock()
        worker.generation = 4
        window._bkg_threads[0] = thread
        window._bkg_workers[0] = worker
        try:
            with patch.object(window, "show_error") as error_mock:
                with patch.object(window, "_dispatch_bkg_worker") as dispatch_mock:
                    window._handle_bkg_error(0, 4, "synthetic failure")
                    window._handle_bkg_thread_finished(0, 4, thread, worker)

            self.assertFalse(window._is_frame_rendering(0))
            error_mock.assert_called_once_with(
                "Background calculation failed", "synthetic failure"
            )
            dispatch_mock.assert_not_called()
        finally:
            window.deleteLater()

    def test_current_bkg_error_replaces_cutout_loading_message(self) -> None:
        window = MainWindow()
        frame = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [frame]
        window._frame_dirty = [False]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._view_mode = "original"
        window._current_frame_index = 0
        window._bkg_generation = 4
        window.source_table_dock = Mock()
        window.source_table_dock.current_cutout_mode.return_value = "Residual"
        try:
            with patch.object(window, "show_error"):
                window._handle_bkg_error(0, 4, "synthetic failure")

            window.source_table_dock.clear_cutout_image.assert_called_once_with(
                "Background unavailable: synthetic failure"
            )
        finally:
            window.deleteLater()

    def test_cancel_bkg_workers_timeout_keeps_running_thread_tracked(self) -> None:
        window = MainWindow()
        thread = Mock()
        thread.isRunning.return_value = True
        thread.wait.return_value = False
        worker = Mock()
        worker.generation = 4
        window._bkg_threads[0] = thread
        window._bkg_workers[0] = worker
        try:
            stopped = window._cancel_bkg_workers(wait=True)

            worker.cancel.assert_called_once_with()
            self.assertFalse(stopped)
            thread.wait.assert_called_once_with(window.BACKGROUND_THREAD_WAIT_MS)
            thread.terminate.assert_not_called()
            self.assertIs(window._bkg_threads[0], thread)
            self.assertIs(window._bkg_workers[0], worker)
        finally:
            window._bkg_threads.clear()
            window._bkg_workers.clear()
            window.deleteLater()

    def test_rapid_frame_switches_share_one_global_live_bkg_worker(self) -> None:
        frames = [
            FITSData(
                path=f"frame-{index}.fits",
                data=np.full((8, 8), index, dtype=np.float32),
            )
            for index in range(5)
        ]
        window = MainWindow()
        window.canvas = Mock()
        window.fits_service.current_data = frames[0]
        window._frames = frames
        window._frame_images = [None] * len(frames)
        window._frame_dirty = [True] * len(frames)
        window._frame_bkg_cache = [None] * len(frames)
        window._frame_residual_cache = [None] * len(frames)
        window._frame_cached_preview_dim = [0] * len(frames)
        window._current_frame_index = 0
        window._view_mode = "background"
        first_compute_entered = threading.Event()
        release_first_compute = threading.Event()
        compute_call_count = 0
        compute_lock = threading.Lock()

        def blocking_background(data, _params):
            nonlocal compute_call_count
            with compute_lock:
                compute_call_count += 1
                call_number = compute_call_count
            if call_number == 1:
                first_compute_entered.set()
                release_first_compute.wait(5)
            background = np.full_like(data, call_number, dtype=np.float32)
            residual = np.asarray(data, dtype=np.float32) - background
            return background, residual, np.zeros_like(background)

        def dispatch_if_missing(index: int, *, playback_bg: bool = False) -> None:
            del playback_bg
            if not window._frame_bkg_cached(index):
                window._dispatch_bkg_worker(index)

        try:
            with patch.object(
                window.sep_service,
                "compute_background",
                side_effect=blocking_background,
            ):
                with patch.object(
                    window,
                    "_schedule_frame_render",
                    side_effect=dispatch_if_missing,
                ):
                    window._dispatch_bkg_worker(0)
                    self._wait_until(first_compute_entered.is_set)

                    for index in range(1, len(frames)):
                        window._current_frame_index = index
                        window.fits_service.current_data = frames[index]
                        window._dispatch_bkg_worker(index)
                        self.assertEqual(len(window._bkg_threads), 1)

                    self.assertIsNotNone(window._pending_bkg_current)
                    self.assertEqual(window._pending_bkg_current[0], 4)
                    with compute_lock:
                        self.assertEqual(compute_call_count, 1)

                    release_first_compute.set()
                    self._wait_until(
                        lambda: (
                            not window._bkg_threads
                            and window._frame_bkg_cache[4] is not None
                        ),
                        timeout=5.0,
                    )

            with compute_lock:
                self.assertEqual(compute_call_count, 2)
            self.assertIsNone(window._frame_bkg_cache[0])
            self.assertIsNotNone(window._frame_bkg_cache[4])
            self.assertIsNone(window._pending_bkg_current)
        finally:
            release_first_compute.set()
            window._is_closing = True
            window._cancel_bkg_workers(wait=True)
            window.deleteLater()

    def test_playback_bkg_request_returns_to_queue_while_global_slot_is_busy(self) -> None:
        frames = [
            FITSData(path=f"frame-{index}.fits", data=np.zeros((2, 2)))
            for index in range(2)
        ]
        window = MainWindow()
        window.frame_player_dock = Mock()
        window.frame_player_dock.is_playing.return_value = True
        window.fits_service.current_data = frames[0]
        window._frames = frames
        window._frame_images = [None, None]
        window._frame_dirty = [True, True]
        window._frame_bkg_cache = [None, None]
        window._frame_residual_cache = [None, None]
        window._frame_cached_preview_dim = [0, 0]
        window._current_frame_index = 0
        window._view_mode = "background"
        window._playback_render_queue = [1]
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        worker.generation = window._bkg_generation
        window._bkg_threads[0] = thread
        window._bkg_workers[0] = worker
        try:
            with patch.object(window, "_launch_bkg_worker") as launch_mock:
                window._pump_playback_render_queue()

            launch_mock.assert_not_called()
            self.assertEqual(window._playback_render_queue, [1])
            self.assertEqual(list(window._bkg_threads), [0])
            worker.cancel.assert_not_called()
        finally:
            window._bkg_threads.clear()
            window._bkg_workers.clear()
            window.deleteLater()

    def test_composite_bkg_demand_resumes_after_global_slot_cleanup(self) -> None:
        frames = [
            FITSData(path=f"frame-{index}.fits", data=np.zeros((2, 2)))
            for index in range(2)
        ]
        window = MainWindow()
        window.fits_service.current_data = frames[0]
        window._frames = frames
        window._frame_dirty = [True, True]
        window._frame_bkg_cache = [None, None]
        window._frame_residual_cache = [None, None]
        window._current_frame_index = 0
        window._view_mode = "background"
        window._frame_layout_mode = "tiled"
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        worker.generation = window._bkg_generation
        window._bkg_threads[0] = thread
        window._bkg_workers[0] = worker
        try:
            with patch.object(window, "_launch_bkg_worker") as launch_mock:
                window._dispatch_bkg_worker(1)

            launch_mock.assert_not_called()
            self.assertTrue(window._frame_dirty[1])
            self.assertEqual(list(window._bkg_threads), [0])

            thread.isRunning.return_value = False
            with patch.object(
                window,
                "_schedule_next_composite_dirty_frame",
            ) as schedule_mock:
                window._handle_bkg_thread_finished(
                    0,
                    worker.generation,
                    thread,
                    worker,
                )

            schedule_mock.assert_called_once_with()
            self.assertEqual(window._bkg_threads, {})
        finally:
            window._bkg_threads.clear()
            window._bkg_workers.clear()
            window.deleteLater()

    def test_start_frame_load_uses_preview_profile_dimension(self) -> None:
        window = MainWindow()
        window._preview_profile_name = "Detailed"
        try:
            with patch.object(window, "_stop_active_frame_load"):
                with patch.object(window, "close_current_file") as close_mock:
                    with patch.object(window, "_set_loading_state"):
                        with patch("astroview.app.main_window.QThread", _FakeThread):
                            with patch("astroview.app.main_window.FITSLoadWorker") as worker_cls:
                                worker_cls.return_value = Mock(
                                    moveToThread=Mock(),
                                    file_loaded=_FakeSignal(),
                                    file_error=_FakeSignal(),
                                    progress=_FakeSignal(),
                                    finished=_FakeSignal(),
                                    deleteLater=Mock(),
                                )
                                window._start_frame_load(["frame.fits"], append=False)

            close_mock.assert_called_once_with()
            self.assertEqual(worker_cls.call_args.kwargs["preview_max_dimension"], 3072)
        finally:
            window.deleteLater()

    def test_start_frame_load_in_append_mode_keeps_current_file_open(self) -> None:
        window = MainWindow()
        try:
            with patch.object(window, "_stop_active_frame_load"):
                with patch.object(window, "close_current_file") as close_mock:
                    with patch.object(window, "_set_loading_state"):
                        with patch("astroview.app.main_window.QThread", _FakeThread):
                            with patch("astroview.app.main_window.FITSLoadWorker") as worker_cls:
                                worker_cls.return_value = Mock(
                                    moveToThread=Mock(),
                                    file_loaded=_FakeSignal(),
                                    file_error=_FakeSignal(),
                                    progress=_FakeSignal(),
                                    finished=_FakeSignal(),
                                    deleteLater=Mock(),
                                )
                                window._start_frame_load(["frame.fits"], append=True)

            close_mock.assert_not_called()
            self.assertEqual(worker_cls.call_args.kwargs["preview_max_dimension"], 2048)
        finally:
            window.deleteLater()

    def test_repeated_frame_load_requests_keep_only_latest_pending_request(self) -> None:
        window = MainWindow()
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        window._load_thread = thread
        window._load_worker = worker
        window._active_load_request_id = 1
        window._load_results_enabled = True
        try:
            with patch.object(window, "_launch_frame_load") as launch_mock:
                with patch.object(window, "_set_loading_state"):
                    window._start_frame_load(["second.fits"], append=False)
                    window._start_frame_load(["latest.fits"], hdu_index=2, append=True)

                launch_mock.assert_not_called()
                self.assertEqual(window._pending_frame_load.paths, ("latest.fits",))
                self.assertEqual(window._pending_frame_load.hdu_index, 2)
                self.assertTrue(window._pending_frame_load.append)

                thread.isRunning.return_value = False
                window._handle_load_thread_finished(1, thread, worker)

            launch_mock.assert_called_once()
            queued = launch_mock.call_args.args[0]
            self.assertEqual(queued.paths, ("latest.fits",))
        finally:
            window._load_thread = None
            window._load_worker = None
            window.deleteLater()

    def test_nonrunning_loader_cleanup_launches_newest_request_only_once(self) -> None:
        window = MainWindow()
        thread = Mock()
        thread.isRunning.return_value = False
        worker = Mock()
        window._load_thread = thread
        window._load_worker = worker
        window._active_load_request_id = 1
        window._pending_frame_load = SimpleNamespace(
            paths=("older-pending.fits",), hdu_index=None, append=False
        )
        try:
            with patch.object(window, "_launch_frame_load") as launch_mock:
                window._start_frame_load(["newest.fits"], append=False)

            launch_mock.assert_called_once()
            queued = launch_mock.call_args.args[0]
            self.assertEqual(queued.paths, ("newest.fits",))
        finally:
            window._load_thread = None
            window._load_worker = None
            window.deleteLater()

    def test_cancelled_frame_load_rejects_already_queued_callbacks(self) -> None:
        window = MainWindow()
        thread = Mock()
        thread.isRunning.return_value = True
        worker = Mock()
        window._load_thread = thread
        window._load_worker = worker
        window._active_load_request_id = 4
        window._load_results_enabled = True
        window._status_activity_kind = "load"
        try:
            with patch.object(window, "_handle_loaded_frame") as loaded_mock:
                window._handle_status_bar_cancel_requested()
                window._handle_loaded_frame_for_request(
                    4,
                    worker,
                    FITSData(path="queued.fits"),
                    None,
                )

            loaded_mock.assert_not_called()
            self.assertFalse(window._is_current_load_request(4, worker))
            self.assertIs(window._load_thread, thread)
        finally:
            window._load_thread = None
            window._load_worker = None
            window.deleteLater()

    def test_handle_frame_preview_rendered_updates_current_image(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame.fits")]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        window._render_generation = 3
        window._latest_render_request_by_index[0] = 11
        window.canvas = Mock()
        try:
            with patch.object(window, "_qimage_from_u8", return_value="preview-image") as qimage_mock:
                with patch.object(window, "_show_current_frame_image") as show_mock:
                    window._handle_frame_preview_rendered(11, 3, 0, "preview-u8")

            self.assertEqual(window._frame_images, ["preview-image"])
            self.assertEqual(window._frame_dirty, [True])
            qimage_mock.assert_called_once_with("preview-u8")
            show_mock.assert_called_once_with()
            window.canvas.set_image_state.assert_called_once()
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
        window.canvas = Mock()
        try:
            with patch.object(window, "_qimage_from_u8", return_value="final-image") as qimage_mock:
                with patch.object(window, "_show_current_frame_image") as show_mock:
                    window._handle_frame_rendered(12, 3, 0, "full-u8")

            self.assertEqual(window._frame_images, ["final-image"])
            self.assertEqual(window._frame_dirty, [False])
            qimage_mock.assert_called_once_with("full-u8")
            show_mock.assert_called_once_with()
            window.canvas.set_image_state.assert_called_once()
        finally:
            window.deleteLater()

    def test_qimage_from_u8_accepts_non_contiguous_arrays(self) -> None:
        window = MainWindow()
        try:
            image_u8 = np.arange(100, dtype=np.uint8).reshape(10, 10)[:, ::2]

            qimage = window._qimage_from_u8(image_u8)

            self.assertIsNotNone(qimage)
            self.assertEqual(qimage.width(), 5)
            self.assertEqual(qimage.height(), 10)
        finally:
            window.deleteLater()

    def test_handle_frame_rendered_prewarms_adjacent_frame_for_current_frame(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame-0.fits"), FITSData(path="frame-1.fits")]
        window._frame_images = [None, None]
        window._frame_dirty = [True, True]
        window._current_frame_index = 0
        window._render_generation = 3
        window._latest_render_request_by_index[0] = 12
        window.canvas = Mock()
        try:
            with patch.object(window, "_qimage_from_u8", return_value="final-image"):
                with patch.object(window, "_show_current_frame_image"):
                    with patch.object(window, "_prewarm_adjacent_frame") as prewarm_mock:
                        window._handle_frame_rendered(12, 3, 0, "full-u8")

            prewarm_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_show_current_frame_image_restores_canvas_view_state_after_image_replace(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.canvas.capture_view_state.return_value = {"scale_factor": 2.0}
        window._frame_images = ["rendered-image"]
        window._current_frame_index = 0
        try:
            window._show_current_frame_image()

            window.canvas.capture_view_state.assert_called_once_with()
            window.canvas.set_image.assert_called_once_with("rendered-image")
            window.canvas.restore_view_state.assert_called_once_with({"scale_factor": 2.0})
        finally:
            window.deleteLater()

    def test_build_composite_frame_image_tiles_loaded_frames(self) -> None:
        window = MainWindow()
        window._frames = [
            FITSData(path="frame-0.fits", data=np.zeros((2, 2))),
            FITSData(path="frame-1.fits", data=np.zeros((2, 2))),
        ]
        window._frame_images = [
            self._grayscale_image([[10, 20], [30, 40]]),
            self._grayscale_image([[50, 60], [70, 80]]),
        ]
        window._frame_layout_mode = "tiled"
        try:
            image = window._build_composite_frame_image()

            self.assertEqual((image.width(), image.height()), (4, 2))
            self.assertEqual(image.pixelColor(0, 0).red(), 10)
            self.assertEqual(image.pixelColor(1, 1).red(), 40)
            self.assertEqual(image.pixelColor(2, 0).red(), 50)
            self.assertEqual(image.pixelColor(3, 1).red(), 80)
        finally:
            window.deleteLater()

    def test_build_composite_frame_image_stacks_loaded_frames_vertically(self) -> None:
        window = MainWindow()
        window._frames = [
            FITSData(path="frame-0.fits", data=np.zeros((2, 2))),
            FITSData(path="frame-1.fits", data=np.zeros((2, 2))),
        ]
        window._frame_images = [
            self._grayscale_image([[1, 2], [3, 4]]),
            self._grayscale_image([[5, 6], [7, 8]]),
        ]
        window._frame_layout_mode = "vertical"
        try:
            image = window._build_composite_frame_image()

            self.assertEqual((image.width(), image.height()), (2, 4))
            self.assertEqual(image.pixelColor(0, 0).red(), 1)
            self.assertEqual(image.pixelColor(1, 1).red(), 4)
            self.assertEqual(image.pixelColor(0, 2).red(), 5)
            self.assertEqual(image.pixelColor(1, 3).red(), 8)
        finally:
            window.deleteLater()

    def test_update_status_from_cursor_samples_frame_under_tiled_composite_layout(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window._frames = [
            FITSData(path="frame-0.fits", data=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)),
            FITSData(path="frame-1.fits", data=np.array([[9.0, 8.0], [7.0, 6.0]], dtype=np.float32)),
        ]
        window._frame_layout_mode = "tiled"
        window.fits_service.current_data = window._frames[0]
        try:
            window.update_status_from_cursor(2.2, 0.4)

            sample = window.app_status_bar.set_sample.call_args.args[0]
            self.assertEqual(sample.x, 0)
            self.assertEqual(sample.y, 0)
            self.assertEqual(sample.value, 9.0)
            self.assertTrue(sample.inside_image)
        finally:
            window.deleteLater()

    def test_build_sep_enablement_state_disables_sep_for_composite_layout(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits")]
        window._frame_layout_mode = "vertical"
        window.fits_service.current_data = FITSData(path="0.fits", data=np.zeros((2, 2)))
        try:
            state = window.build_sep_enablement_state()

            self.assertFalse(state.enabled)
            self.assertIn("composite", state.reason.lower())
        finally:
            window.deleteLater()

    def test_sync_catalog_views_hides_canvas_sources_in_composite_layout(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits")]
        window._frame_layout_mode = "tiled"
        window.current_catalog = SourceCatalog(records=[SourceRecord(source_id=1, x=10.0, y=12.0)])
        try:
            window.sync_catalog_views()

            window.canvas.clear_sources.assert_called_once_with()
            window.canvas.draw_sources.assert_not_called()
        finally:
            window.deleteLater()

    def test_sync_current_canvas_image_state_updates_frame_player_render_state(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.frame_player_dock = Mock()
        window.frame_player_dock.is_playing.return_value = False
        window._frames = [FITSData(path="frame.fits")]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        try:
            window._sync_current_canvas_image_state()

            window.canvas.set_image_state.assert_called_once()
            window.frame_player_dock.set_render_state.assert_called_once_with(True, has_preview=False)
        finally:
            window.deleteLater()

    def test_schedule_frame_render_skips_non_current_frame_when_current_render_is_active(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame-0.fits"), FITSData(path="frame-1.fits")]
        window._frame_images = [None, None]
        window._frame_dirty = [True, True]
        window._current_frame_index = 0
        running_thread = Mock()
        running_thread.isRunning.return_value = True
        window._render_threads[8] = running_thread
        window._render_request_index_by_id[8] = 0
        window._latest_render_request_by_index[0] = 8
        try:
            with patch("astroview.app.main_window.FrameRenderWorker") as worker_cls:
                window._schedule_frame_render(1)

            worker_cls.assert_not_called()
            self.assertIn(8, window._render_threads)
            self.assertNotIn(1, window._latest_render_request_by_index)
        finally:
            window.deleteLater()

    def test_schedule_frame_render_uses_configured_preview_dimensions(self) -> None:
        window = MainWindow()
        window._preview_profile_name = "Fast"
        window._frames = [FITSData(path="frame-0.fits")]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        try:
            with patch("astroview.app.main_window.QThread", _FakeThread):
                with patch("astroview.app.main_window.FrameRenderWorker") as worker_cls:
                    worker_cls.return_value = Mock(
                        moveToThread=Mock(),
                        preview_ready=_FakeSignal(),
                        render_ready=_FakeSignal(),
                        render_error=_FakeSignal(),
                        finished=_FakeSignal(),
                        deleteLater=Mock(),
                    )
                    window._schedule_frame_render(0)

            self.assertEqual(worker_cls.call_args.kwargs["preview_dimensions"], (1024,))
        finally:
            window.deleteLater()

    def test_schedule_frame_render_runs_worker_on_real_qthread_and_cleans_up(self) -> None:
        frame = FITSData(path="frame-0.fits", data=np.zeros((2, 2)))
        window = MainWindow()
        window.canvas = Mock()
        window.fits_service.current_data = frame
        window._frames = [frame]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        converted: list[object] = []

        def convert(image_u8: object) -> object:
            converted.append(image_u8)
            return image_u8

        try:
            with patch("astroview.app.frame_render_worker.render_preview_u8", side_effect=["preview-1024", "preview-2048"]):
                with patch("astroview.app.frame_render_worker.render_image_u8", return_value="full-render"):
                    with patch.object(window, "_qimage_from_u8", side_effect=convert):
                        with patch.object(window, "_prewarm_adjacent_frame") as prewarm_mock:
                            window._schedule_frame_render(0)
                            request_id = window._latest_render_request_by_index[0]
                            self._wait_until(
                                lambda: request_id not in window._render_threads and window._frame_dirty == [False]
                            )

            self.assertEqual(converted, ["preview-1024", "preview-2048", "full-render"])
            self.assertEqual(window._frame_images, ["full-render"])
            self.assertEqual(window._frame_dirty, [False])
            self.assertNotIn(request_id, window._render_threads)
            self.assertNotIn(request_id, window._render_request_index_by_id)
            prewarm_mock.assert_called_once_with()
        finally:
            window._cancel_active_frame_renders(wait=True)
            window.deleteLater()

    def test_repeated_rerender_coalesces_to_one_live_worker_per_frame(self) -> None:
        frame = FITSData(path="frame-0.fits", data=np.zeros((8, 8), dtype=np.float32))
        window = MainWindow()
        window.canvas = Mock()
        window.fits_service.current_data = frame
        window._frames = [frame]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._frame_bkg_cache = [None]
        window._frame_residual_cache = [None]
        window._frame_cached_preview_dim = [0]
        window._current_frame_index = 0
        first_compute_entered = threading.Event()
        release_first_compute = threading.Event()
        compute_call_count = 0
        compute_lock = threading.Lock()

        def blocking_limits(*_args, **_kwargs):
            nonlocal compute_call_count
            with compute_lock:
                compute_call_count += 1
                call_number = compute_call_count
            if call_number == 1:
                first_compute_entered.set()
                release_first_compute.wait(5)
            return (0.0, 1.0)

        try:
            with patch(
                "astroview.app.frame_render_worker.compute_interval_limits",
                side_effect=blocking_limits,
            ):
                with patch(
                    "astroview.app.frame_render_worker.render_preview_u8",
                    return_value=None,
                ):
                    with patch(
                        "astroview.app.frame_render_worker.render_image_u8",
                        return_value="latest-full-render",
                    ):
                        with patch.object(
                            window,
                            "_qimage_from_u8",
                            side_effect=lambda image: image,
                        ):
                            with patch.object(window, "_show_current_frame_image"):
                                window._schedule_frame_render(0)
                                self._wait_until(first_compute_entered.is_set)

                                for _ in range(5):
                                    window._rerender_all_frames()

                                self.assertEqual(len(window._render_threads), 1)
                                self.assertEqual(
                                    len(window._active_render_request_by_index),
                                    1,
                                )
                                self.assertEqual(
                                    window._pending_render_intent,
                                    (0, window._render_generation, False),
                                )
                                with compute_lock:
                                    self.assertEqual(compute_call_count, 1)

                                release_first_compute.set()
                                self._wait_until(
                                    lambda: (
                                        not window._render_threads
                                        and window._frame_dirty == [False]
                                    ),
                                    timeout=5.0,
                                )

            with compute_lock:
                self.assertEqual(compute_call_count, 2)
            self.assertEqual(window._frame_images, ["latest-full-render"])
            self.assertEqual(window._active_render_request_by_index, {})
            self.assertIsNone(window._pending_render_intent)
        finally:
            release_first_compute.set()
            window._cancel_active_frame_renders(wait=True)
            window.deleteLater()

    def test_rapid_frame_switches_share_one_global_live_render_worker(self) -> None:
        frames = [
            FITSData(path=f"frame-{index}.fits", data=np.zeros((8, 8), dtype=np.float32))
            for index in range(5)
        ]
        window = MainWindow()
        window.canvas = Mock()
        window.fits_service.current_data = frames[0]
        window._frames = frames
        window._frame_images = [None] * len(frames)
        window._frame_dirty = [True] * len(frames)
        window._frame_bkg_cache = [None] * len(frames)
        window._frame_residual_cache = [None] * len(frames)
        window._frame_cached_preview_dim = [0] * len(frames)
        first_compute_entered = threading.Event()
        release_first_compute = threading.Event()
        compute_call_count = 0
        compute_lock = threading.Lock()

        def blocking_limits(*_args, **_kwargs):
            nonlocal compute_call_count
            with compute_lock:
                compute_call_count += 1
                call_number = compute_call_count
            if call_number == 1:
                first_compute_entered.set()
                release_first_compute.wait(5)
            return (0.0, 1.0)

        try:
            with patch(
                "astroview.app.frame_render_worker.compute_interval_limits",
                side_effect=blocking_limits,
            ):
                with patch(
                    "astroview.app.frame_render_worker.render_preview_u8",
                    return_value=None,
                ):
                    with patch(
                        "astroview.app.frame_render_worker.render_image_u8",
                        return_value="latest-frame-render",
                    ):
                        with patch.object(
                            window,
                            "_qimage_from_u8",
                            side_effect=lambda image: image,
                        ):
                            with patch.object(window, "_show_current_frame_image"):
                                window._current_frame_index = 0
                                window._schedule_frame_render(0)
                                self._wait_until(first_compute_entered.is_set)

                                for index in range(1, len(frames)):
                                    window._current_frame_index = index
                                    window.fits_service.current_data = frames[index]
                                    window._schedule_frame_render(index)
                                    self.assertEqual(len(window._render_threads), 1)

                                self.assertEqual(
                                    window._pending_render_intent,
                                    (4, window._render_generation, False),
                                )
                                with compute_lock:
                                    self.assertEqual(compute_call_count, 1)

                                release_first_compute.set()
                                self._wait_until(
                                    lambda: (
                                        not window._render_threads
                                        and window._frame_dirty[4] is False
                                    ),
                                    timeout=5.0,
                                )

            with compute_lock:
                self.assertEqual(compute_call_count, 2)
            self.assertEqual(window._frame_images[4], "latest-frame-render")
            self.assertIsNone(window._pending_render_intent)
        finally:
            release_first_compute.set()
            window._cancel_active_frame_renders(wait=True)
            window.deleteLater()

    def test_playback_queue_uses_global_render_slot_serially(self) -> None:
        frames = [
            FITSData(path=f"frame-{index}.fits", data=np.zeros((8, 8), dtype=np.float32))
            for index in range(3)
        ]
        window = MainWindow()
        window.canvas = Mock()
        window.frame_player_dock = Mock()
        window.frame_player_dock.is_playing.return_value = True
        window.fits_service.current_data = frames[0]
        window._frames = frames
        window._frame_images = [None] * len(frames)
        window._frame_dirty = [True] * len(frames)
        window._frame_bkg_cache = [None] * len(frames)
        window._frame_residual_cache = [None] * len(frames)
        window._frame_cached_preview_dim = [0] * len(frames)
        window._current_frame_index = 0
        entered = [threading.Event() for _ in frames]
        releases = [threading.Event() for _ in frames]
        rendered_paths: list[str] = []
        call_lock = threading.Lock()

        def staged_limits(data, *_args, **_kwargs):
            with call_lock:
                call_index = len(rendered_paths)
                rendered_paths.append(data.path)
            entered[call_index].set()
            releases[call_index].wait(5)
            return (0.0, 1.0)

        try:
            with patch(
                "astroview.app.frame_render_worker.compute_interval_limits",
                side_effect=staged_limits,
            ):
                with patch(
                    "astroview.app.frame_render_worker.render_preview_u8",
                    return_value=None,
                ):
                    with patch(
                        "astroview.app.frame_render_worker.render_image_u8",
                        return_value="playback-render",
                    ):
                        with patch.object(
                            window,
                            "_qimage_from_u8",
                            side_effect=lambda image: image,
                        ):
                            with patch.object(window, "_show_current_frame_image"):
                                with patch.object(window, "_prewarm_adjacent_frame"):
                                    window._build_playback_render_queue()
                                    window._pump_playback_render_queue()

                                    for index in range(len(frames)):
                                        self._wait_until(entered[index].is_set)
                                        self.assertEqual(len(window._render_threads), 1)
                                        releases[index].set()

                                    self._wait_until(
                                        lambda: (
                                            not window._render_threads
                                            and window._frame_dirty == [False, False, False]
                                        ),
                                        timeout=5.0,
                                    )

            self.assertEqual(
                rendered_paths,
                ["frame-1.fits", "frame-2.fits", "frame-0.fits"],
            )
            self.assertEqual(window._playback_render_queue, [])
        finally:
            for release in releases:
                release.set()
            window._is_closing = True
            window._cancel_active_frame_renders(wait=True)
            window.deleteLater()

    def test_composite_queue_uses_global_render_slot_serially(self) -> None:
        frames = [
            FITSData(path=f"frame-{index}.fits", data=np.zeros((8, 8), dtype=np.float32))
            for index in range(3)
        ]
        window = MainWindow()
        window.canvas = Mock()
        window.fits_service.current_data = frames[0]
        window._frames = frames
        window._frame_images = [None] * len(frames)
        window._frame_dirty = [True] * len(frames)
        window._frame_bkg_cache = [None] * len(frames)
        window._frame_residual_cache = [None] * len(frames)
        window._frame_cached_preview_dim = [0] * len(frames)
        window._current_frame_index = 0
        window._frame_layout_mode = "tiled"
        entered = [threading.Event() for _ in frames]
        releases = [threading.Event() for _ in frames]
        rendered_paths: list[str] = []
        call_lock = threading.Lock()

        def staged_limits(data, *_args, **_kwargs):
            with call_lock:
                call_index = len(rendered_paths)
                rendered_paths.append(data.path)
            entered[call_index].set()
            releases[call_index].wait(5)
            return (0.0, 1.0)

        try:
            with patch(
                "astroview.app.frame_render_worker.compute_interval_limits",
                side_effect=staged_limits,
            ):
                with patch(
                    "astroview.app.frame_render_worker.render_preview_u8",
                    return_value=None,
                ):
                    with patch(
                        "astroview.app.frame_render_worker.render_image_u8",
                        return_value="composite-render",
                    ):
                        with patch.object(
                            window,
                            "_qimage_from_u8",
                            side_effect=lambda image: image,
                        ):
                            with patch.object(window, "_show_current_frame_image"):
                                with patch.object(window, "_prewarm_adjacent_frame"):
                                    window._schedule_next_composite_dirty_frame()

                                    for index in range(len(frames)):
                                        self._wait_until(entered[index].is_set)
                                        self.assertEqual(len(window._render_threads), 1)
                                        releases[index].set()

                                    self._wait_until(
                                        lambda: (
                                            not window._render_threads
                                            and window._frame_dirty == [False, False, False]
                                        ),
                                        timeout=5.0,
                                    )

            self.assertEqual(
                rendered_paths,
                ["frame-0.fits", "frame-1.fits", "frame-2.fits"],
            )
        finally:
            for release in releases:
                release.set()
            window._is_closing = True
            window._cancel_active_frame_renders(wait=True)
            window.deleteLater()

    def test_close_current_file_cancels_active_loading_and_rendering(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.source_table_dock = Mock()
        window.header_dialog = Mock()
        window.app_status_bar = Mock()
        window.frame_player_dock = Mock()
        window.sep_panel = Mock()
        window._frames = [FITSData(path="frame-0.fits")]
        window._frame_images = ["preview-image"]
        window._frame_dirty = [True]
        window._render_request_index_by_id = {4: 0}
        window._latest_render_request_by_index = {0: 4}
        window._render_workers = {4: Mock()}
        generation_before = window._render_generation
        try:
            with patch.object(window, "_stop_active_frame_load") as stop_load_mock:
                with patch.object(window, "_cancel_active_frame_renders") as cancel_renders_mock:
                    with patch.object(window, "sync_sep_panel_state") as sync_sep_mock:
                        with patch.object(window, "sync_render_controls") as sync_render_mock:
                            window.close_current_file()

            stop_load_mock.assert_called_once_with(wait=False)
            cancel_renders_mock.assert_called_once_with(wait=False)
            self.assertEqual(window._render_generation, generation_before + 1)
            self.assertEqual(window._render_request_index_by_id, {})
            self.assertEqual(window._latest_render_request_by_index, {})
            self.assertEqual(window._render_workers, {})
            self.assertEqual(window._frames, [])
            self.assertEqual(window._frame_images, [])
            self.assertEqual(window._frame_dirty, [])
            self.assertEqual(window._current_frame_index, 0)
            self.assertEqual(window.windowTitle(), f"AstroView v{__version__}")
            sync_sep_mock.assert_called_once_with()
            sync_render_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_show_header_dialog_uses_structured_payloads_and_current_hdu(self) -> None:
        window = MainWindow()
        window.header_dialog = Mock()
        window.fits_service.current_data = FITSData(path="demo.fits", hdu_index=2)
        payloads = [HeaderPayload(hdu_index=2, name="SCI", kind="ImageHDU", raw_text="OBJECT = 'M31'")]
        state = HeaderViewState(has_header=True, hdu_index=2, line_count=1)
        try:
            with patch.object(window, "build_header_view_state", return_value=state) as state_mock:
                with patch.object(window, "_build_header_payloads", return_value=payloads) as payload_mock:
                    window.show_header_dialog()

            state_mock.assert_called_once_with()
            payload_mock.assert_called_once_with()
            window.header_dialog.set_view_state.assert_called_once_with(state)
            window.header_dialog.set_header_payloads.assert_called_once_with(payloads, current_hdu_index=2)
            window.header_dialog.show.assert_called_once_with()
            window.header_dialog.raise_.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_header_payloads_fall_back_when_loaded_path_is_replaced_by_gzip(self) -> None:
        from astropy.io import fits

        with TemporaryDirectory() as directory:
            path = Path(directory) / "replaced.fits"
            hdu = fits.PrimaryHDU(data=np.arange(4, dtype=np.float32).reshape(2, 2))
            hdu.header["OBJECT"] = "ORIGINAL"
            hdu.writeto(path)
            loaded = FITSData.load(str(path))

            path.write_bytes(gzip.compress(path.read_bytes()))
            window = MainWindow()
            window.fits_service.current_data = loaded
            try:
                with patch("astroview.core.fits_data._astropy_fits") as astropy_mock:
                    with patch("astroview.app.main_window.logger.exception"):
                        payloads = window._build_header_payloads()

                astropy_mock.assert_not_called()
                self.assertEqual(len(payloads), 1)
                self.assertEqual(payloads[0].hdu_index, 0)
                self.assertEqual(payloads[0].name, "HDU 0")
                self.assertIn("ORIGINAL", payloads[0].raw_text)
                self.assertEqual(payloads[0].raw_text, loaded.header_as_text())
            finally:
                window.deleteLater()

    def test_activate_frame_includes_version_in_window_title(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame-0.fits")]
        window._frame_images = [None]
        window._frame_dirty = [False]
        window.canvas = Mock()
        window.app_status_bar = Mock()
        try:
            with patch.object(window, "_show_current_frame_image"):
                with patch.object(window, "sync_render_controls"):
                    window._activate_frame(0)

            self.assertEqual(window.windowTitle(), f"AstroView v{__version__} - frame-0.fits")
        finally:
            window.deleteLater()

    def test_schedule_frame_render_cancels_stale_other_frame_requests_for_current_frame(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="frame-0.fits"), FITSData(path="frame-1.fits")]
        window._frame_images = [None, None]
        window._frame_dirty = [True, True]
        window._current_frame_index = 1
        stale_thread = Mock()
        stale_thread.isRunning.return_value = True
        window._render_threads[8] = stale_thread
        window._render_request_index_by_id[8] = 0
        window._latest_render_request_by_index[0] = 8
        try:
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

            stale_thread.requestInterruption.assert_called_once_with()
            stale_thread.quit.assert_called_once_with()
            worker_cls.assert_not_called()
            self.assertEqual(
                window._pending_render_intent,
                (1, window._render_generation, False),
            )
            self.assertNotIn(1, window._latest_render_request_by_index)
        finally:
            window.deleteLater()

    def test_preferred_adjacent_frame_index_uses_recent_forward_direction(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 1
        window._frame_step_direction = 1
        try:
            self.assertEqual(window._preferred_adjacent_frame_index(), 2)
        finally:
            window.deleteLater()

    def test_preferred_adjacent_frame_index_wraps_in_loop_mode(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 2
        window._frame_step_direction = 1
        window.frame_player_dock = Mock()
        window.frame_player_dock.bounce_btn.isChecked.return_value = False
        window.frame_player_dock.loop_btn.isChecked.return_value = True
        try:
            self.assertEqual(window._preferred_adjacent_frame_index(), 0)
        finally:
            window.deleteLater()

    def test_preferred_adjacent_frame_index_reflects_bounce_direction(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 2
        window._frame_step_direction = 1
        window.frame_player_dock = Mock()
        window.frame_player_dock.bounce_btn.isChecked.return_value = True
        window.frame_player_dock.loop_btn.isChecked.return_value = False
        try:
            self.assertEqual(window._preferred_adjacent_frame_index(), 1)
        finally:
            window.deleteLater()

    def test_prewarm_adjacent_frame_schedules_likely_next_dirty_frame(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._frame_dirty = [False, False, True]
        window._current_frame_index = 1
        window._frame_step_direction = 1
        try:
            with patch.object(window, "_schedule_frame_render") as schedule_mock:
                window._prewarm_adjacent_frame()

            schedule_mock.assert_called_once_with(2)
        finally:
            window.deleteLater()

    def test_switch_frame_updates_recent_step_direction_on_loop_wrap(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 2
        window.frame_player_dock = Mock()
        try:
            with patch.object(window, "_activate_frame") as activate_mock:
                window._switch_frame(0)

            self.assertEqual(window._frame_step_direction, 1)
            activate_mock.assert_called_once_with(0)
        finally:
            window.deleteLater()

    def test_go_prev_frame_wraps_from_first_frame_to_last(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 0
        try:
            with patch.object(window, "_switch_frame") as switch_mock:
                window._go_prev_frame()

            switch_mock.assert_called_once_with(2)
        finally:
            window.deleteLater()

    def test_go_prev_frame_pauses_playback_before_switching(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 0
        window.frame_player_dock = Mock()
        window.frame_player_dock.is_playing.return_value = True
        try:
            with patch.object(window, "_switch_frame") as switch_mock:
                window._go_prev_frame()

            window.frame_player_dock.stop_playback.assert_called_once_with()
            switch_mock.assert_called_once_with(2)
        finally:
            window.deleteLater()

    def test_go_next_frame_wraps_from_last_frame_to_first(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 2
        try:
            with patch.object(window, "_switch_frame") as switch_mock:
                window._go_next_frame()

            switch_mock.assert_called_once_with(0)
        finally:
            window.deleteLater()

    def test_go_next_frame_pauses_playback_before_switching(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="0.fits"), FITSData(path="1.fits"), FITSData(path="2.fits")]
        window._current_frame_index = 2
        window.frame_player_dock = Mock()
        window.frame_player_dock.is_playing.return_value = True
        try:
            with patch.object(window, "_switch_frame") as switch_mock:
                window._go_next_frame()

            window.frame_player_dock.stop_playback.assert_called_once_with()
            switch_mock.assert_called_once_with(0)
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

    def test_create_file_actions_assigns_legacy_region_shortcut_to_csv_export(self) -> None:
        window = MainWindow()
        try:
            window.create_file_actions()

            shortcuts = [shortcut.toString() for shortcut in window.action_export_catalog.shortcuts()]
            self.assertEqual(shortcuts, ["Ctrl+E", "Ctrl+Shift+E"])
            self.assertEqual(window.action_reopen_last_session.text(), "Reopen Last Session")
        finally:
            window.deleteLater()

    def test_create_view_actions_registers_wrapped_frame_navigation_shortcuts(self) -> None:
        window = MainWindow()
        try:
            window.create_view_actions()

            self.assertIn(window.action_prev_frame, window.actions())
            self.assertIn(window.action_next_frame, window.actions())
            self.assertEqual(
                [shortcut.toString() for shortcut in window.action_prev_frame.shortcuts()],
                ["Left", "A"],
            )
            self.assertEqual(
                [shortcut.toString() for shortcut in window.action_next_frame.shortcuts()],
                ["Right", "D"],
            )
            self.assertTrue(window.action_frame_layout_single.isCheckable())
            self.assertTrue(window.action_frame_layout_tiled.isCheckable())
            self.assertTrue(window.action_frame_layout_vertical.isCheckable())
        finally:
            window.deleteLater()

    def test_reopen_last_session_uses_persisted_paths_and_index(self) -> None:
        window = MainWindow()
        window._settings = Mock()

        def value_side_effect(key, default=None, type=None):
            values = {
                "session/last_paths": ["D:\\fits\\a.fits", "D:\\fits\\b.fits"],
                "session/current_index": 1,
            }
            return values.get(key, default)

        window._settings.value.side_effect = value_side_effect
        try:
            with patch.object(window, "_open_paths") as open_mock:
                window._reopen_last_session()

            self.assertEqual(window._pending_session_restore_frame_index, 1)
            open_mock.assert_called_once_with(["D:\\fits\\a.fits", "D:\\fits\\b.fits"], append=False)
        finally:
            window.deleteLater()

    def test_persist_session_state_collapses_multiframe_cube_paths(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window._frames = [
            FITSData(path="D:\\fits\\cube.fits", frame_index=0, frame_count=3, source_group_id=5),
            FITSData(path="D:\\fits\\cube.fits", frame_index=1, frame_count=3, source_group_id=5),
            FITSData(path="D:\\fits\\cube.fits", frame_index=2, frame_count=3, source_group_id=5),
            FITSData(path="D:\\fits\\other.fits", frame_index=0, frame_count=1, source_group_id=6),
        ]
        window._current_frame_index = 2
        try:
            window._persist_session_state()

            self._assert_settings_write(
                window._settings,
                "session/last_paths",
                ["D:\\fits\\cube.fits", "D:\\fits\\other.fits"],
            )
            self._assert_settings_write(window._settings, "session/current_index", 2)
        finally:
            window.deleteLater()

    def test_create_help_actions_defines_check_updates_action(self) -> None:
        window = MainWindow()
        try:
            window.create_help_actions()

            self.assertEqual(window.action_check_updates.text(), "Check for Updates...")
        finally:
            window.deleteLater()

    def test_handle_language_changed_persists_setting_and_prompts_for_restart(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        try:
            with patch("astroview.app.main_window.current_language", return_value="en"):
                with patch("astroview.app.main_window.QMessageBox.information") as info_mock:
                    window._handle_language_changed("zh_CN", True)

            self._assert_settings_write(window._settings, "ui/language", "zh_CN")
            info_mock.assert_called_once_with(
                window,
                "Language",
                "Language change will take effect after restart.",
            )
        finally:
            window.deleteLater()

    def test_handle_update_check_result_opens_release_page_when_confirmed(self) -> None:
        window = MainWindow()
        try:
            result = UpdateCheckResult(
                status="update_available",
                current_version=__version__,
                latest_version="9.9.9",
                release_url="https://example.com/releases/tag/v9.9.9",
                detail="A newer version is available.",
            )
            with patch(
                "astroview.app.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                with patch("astroview.app.main_window.QDesktopServices.openUrl") as open_mock:
                    window._handle_update_check_result(result)

            open_mock.assert_called_once()
        finally:
            window.deleteLater()

    def test_stale_update_check_callbacks_cannot_clear_or_report_for_new_worker(self) -> None:
        window = MainWindow()
        old_thread = Mock()
        old_worker = Mock()
        new_thread = Mock()
        new_worker = Mock()
        window._active_update_check_request_id = 2
        window._update_check_thread = new_thread
        window._update_check_worker = new_worker
        result = UpdateCheckResult(status="up_to_date", current_version=__version__)
        try:
            with patch.object(window, "_handle_update_check_result") as handle_mock:
                window._handle_update_check_result_for_request(1, old_worker, result)
                window._clear_update_check_refs(1, old_thread, old_worker)

            handle_mock.assert_not_called()
            self.assertIs(window._update_check_thread, new_thread)
            self.assertIs(window._update_check_worker, new_worker)
            self.assertEqual(window._active_update_check_request_id, 2)
        finally:
            window._update_check_thread = None
            window._update_check_worker = None
            window.deleteLater()

    def test_update_check_timeout_keeps_running_thread_tracked_without_terminate(self) -> None:
        window = MainWindow()
        thread = Mock()
        thread.isRunning.return_value = True
        thread.wait.return_value = False
        worker = Mock()
        window._active_update_check_request_id = 4
        window._update_check_thread = thread
        window._update_check_worker = worker
        try:
            stopped = window._stop_update_check(wait=True)

            self.assertFalse(stopped)
            worker.cancel.assert_called_once_with()
            thread.requestInterruption.assert_called_once_with()
            thread.quit.assert_called_once_with()
            thread.wait.assert_called_once_with(window.UPDATE_CHECK_THREAD_WAIT_MS)
            thread.terminate.assert_not_called()
            self.assertIs(window._update_check_thread, thread)
            self.assertIs(window._update_check_worker, worker)
        finally:
            window._update_check_thread = None
            window._update_check_worker = None
            window._active_update_check_request_id = None
            window.deleteLater()

    def test_update_result_relay_runs_dialog_handler_on_gui_thread(self) -> None:
        window = MainWindow()
        thread = QThread()
        worker = _ThreadUpdateEmitter()
        worker.moveToThread(thread)
        relay = _UpdateCheckSignalRelay(window, 1, thread, worker)
        window._active_update_check_request_id = 1
        window._update_check_thread = thread
        window._update_check_worker = worker
        handler_threads: list[QThread] = []
        cleanup_threads: list[QThread] = []
        try:
            thread.started.connect(worker.run)
            worker.result_ready.connect(relay.handle_result)
            worker.finished.connect(worker.deleteLater)
            worker.finished.connect(thread.quit)
            thread.finished.connect(relay.handle_thread_finished)
            thread.finished.connect(relay.deleteLater)

            with patch.object(
                window,
                "_handle_update_check_result",
                side_effect=lambda _result: handler_threads.append(QThread.currentThread()),
            ):
                with patch.object(
                    window,
                    "_clear_update_check_refs",
                    side_effect=lambda *_args: cleanup_threads.append(QThread.currentThread()),
                ):
                    thread.start()
                    self._wait_until(
                        lambda: bool(handler_threads)
                        and bool(cleanup_threads)
                        and not thread.isRunning()
                    )

            self.assertIs(handler_threads[0], window.thread())
            self.assertIs(cleanup_threads[0], window.thread())
        finally:
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                thread.wait(3000)
            window._update_check_thread = None
            window._update_check_worker = None
            window._active_update_check_request_id = None
            thread.deleteLater()
            window.deleteLater()

    def test_handle_source_color_changed_updates_canvas_roi_color(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.marker_dock = Mock()
        window.marker_dock.source_color.return_value = QColor("#00ff00")
        window.marker_dock.source_line_width.return_value = 5
        try:
            window._handle_source_color_changed(QColor("#00ff00"))

            window.canvas.set_roi_color.assert_called_once()
            self.assertEqual(window.canvas.set_roi_color.call_args.args[0].name(), "#00ff00")
            window.canvas.set_source_overlay_style.assert_called_once()
        finally:
            window.deleteLater()

    def test_handle_marker_color_changed_does_not_touch_roi_overlay(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.marker_dock = Mock()
        window.marker_dock.parse_coordinates.return_value = []
        try:
            window._handle_marker_color_changed(QColor("#00ff00"))

            window.canvas.set_roi_color.assert_not_called()
            window.canvas.set_source_overlay_style.assert_not_called()
        finally:
            window.deleteLater()

    def test_update_source_cutout_renders_selected_source_preview(self) -> None:
        window = MainWindow()
        window.source_table_dock = Mock()
        window.source_table_dock.current_selection_state.return_value = SimpleNamespace(selected_row=0)
        window.source_table_dock.current_cutout_mode.return_value = "Intensity"
        window.current_catalog = SourceCatalog(
            records=[SourceRecord(source_id=1, x=25.0, y=25.0)]
        )
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((50, 60), dtype=np.float32))
        try:
            with patch("astroview.core.fits_service.render_image_u8", return_value="cutout-u8") as render_mock:
                with patch.object(window, "_qimage_from_u8", return_value="cutout-qimage") as qimage_mock:
                    window._update_source_cutout()

            render_data = render_mock.call_args.args[0]
            self.assertEqual(render_data.data.shape, (33, 33))
            qimage_mock.assert_called_once_with("cutout-u8")
            window.source_table_dock.set_cutout_image.assert_called_once_with("cutout-qimage")
        finally:
            window.deleteLater()

    def test_update_source_cutout_can_render_connected_region(self) -> None:
        window = MainWindow()
        window.source_table_dock = Mock()
        window.source_table_dock.current_selection_state.return_value = SimpleNamespace(selected_row=0)
        window.source_table_dock.current_cutout_mode.return_value = "Connected Region"
        segmap = np.zeros((20, 20), dtype=np.int32)
        segmap[4:7, 4:7] = 1
        segmap[8:10, 8:10] = 2
        window.current_catalog = SourceCatalog(
            records=[SourceRecord(
                source_id=1,
                x=25.0,
                y=25.0,
                extra={"xmin": 24, "xmax": 26, "ymin": 24, "ymax": 26},
            )],
            segmentation_map=segmap,
            roi_x0=20,
            roi_y0=20,
        )
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((50, 60), dtype=np.float32))
        try:
            with patch.object(window, "_qimage_from_u8", return_value="connected-qimage") as qimage_mock:
                window._update_source_cutout()

            image_u8 = qimage_mock.call_args.args[0]
            self.assertEqual(image_u8.shape, (11, 11))
            self.assertEqual(int(image_u8[4, 4]), 255)
            self.assertEqual(int(image_u8[8, 8]), 96)
            self.assertEqual(int(image_u8[0, 0]), 0)
            window.source_table_dock.set_cutout_image.assert_called_once_with("connected-qimage")
        finally:
            window.deleteLater()

    def test_canvas_source_double_click_selects_matching_source_table_row(self) -> None:
        window = MainWindow()
        try:
            window.initialize(apply_startup_request=False)
            window.current_catalog = SourceCatalog(records=[
                SourceRecord(source_id=1, x=10.0, y=12.0),
                SourceRecord(source_id=2, x=30.0, y=32.0),
            ])
            window.sync_catalog_views()

            window.canvas.source_double_clicked.emit(1)

            self.assertEqual(window.source_table_dock.current_selection_state().selected_row, 1)
            self.assertEqual(window.canvas.overlay_state.highlighted_index, 1)
        finally:
            window.deleteLater()

    def test_handle_source_clicked_centers_canvas_on_selected_source(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.source_table_dock = Mock()
        window.source_table_dock.current_selection_state.return_value = SimpleNamespace(selected_row=None)
        try:
            with patch.object(window, "_update_source_cutout") as cutout_mock:
                window.handle_source_clicked(2)

            window.canvas.highlight_source.assert_called_once_with(2)
            window.canvas.center_on_source.assert_called_once_with(2)
            window.source_table_dock.select_source.assert_called_once_with(2)
            cutout_mock.assert_called_once_with(2)
        finally:
            window.deleteLater()

    def test_visible_source_table_columns_always_include_id_x_y(self) -> None:
        window = MainWindow()
        window.source_table_dock = Mock(
            columns=[
                TableColumnSpec(key="ID", title="ID", visible=False),
                TableColumnSpec(key="X", title="X", visible=False),
                TableColumnSpec(key="Y", title="Y", visible=False),
                TableColumnSpec(key="Flux", title="Flux", visible=True),
            ]
        )
        window.source_table_dock.MANDATORY_COLUMN_KEYS = ("ID", "X", "Y")
        try:
            self.assertEqual(window._visible_source_table_columns(), ["ID", "X", "Y", "Flux"])
        finally:
            window.deleteLater()

    def test_build_canvas_image_state_reports_loading_before_preview_is_ready(self) -> None:
        window = MainWindow()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [window.fits_service.current_data]
        window._frame_images = [None]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        try:
            state = window.build_canvas_image_state()

            self.assertTrue(state.has_image)
            self.assertEqual(state.feedback.status, "loading")
            self.assertEqual(state.feedback.title, "Rendering Preview")
            self.assertTrue(state.feedback.visible)
        finally:
            window.deleteLater()

    def test_build_empty_image_feedback_includes_drop_and_roi_hints(self) -> None:
        window = MainWindow()
        try:
            feedback = window.build_empty_image_feedback()

            self.assertIn("Drop FITS files here", feedback.detail)
            self.assertIn("Ctrl+O", feedback.detail)
            self.assertIn("right-drag a ROI", feedback.detail)
        finally:
            window.deleteLater()

    def test_build_canvas_image_state_reports_loading_after_preview_is_ready(self) -> None:
        window = MainWindow()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [window.fits_service.current_data]
        window._frame_images = ["preview-image"]
        window._frame_dirty = [True]
        window._current_frame_index = 0
        try:
            state = window.build_canvas_image_state()

            self.assertEqual(state.feedback.status, "loading")
            self.assertEqual(state.feedback.title, "Rendering Full Frame")
            self.assertTrue(state.feedback.visible)
        finally:
            window.deleteLater()

    def test_build_canvas_image_state_reports_ready_after_render_finishes(self) -> None:
        window = MainWindow()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        window._frames = [window.fits_service.current_data]
        window._frame_images = ["final-image"]
        window._frame_dirty = [False]
        window._current_frame_index = 0
        try:
            state = window.build_canvas_image_state()

            self.assertEqual(state.feedback.status, "ready")
            self.assertFalse(state.feedback.visible)
        finally:
            window.deleteLater()

    def test_rerender_all_frames_updates_current_canvas_feedback_to_loading(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window._frames = [FITSData(path="frame.fits")]
        window._frame_images = ["old-image"]
        window._frame_dirty = [False]
        window._current_frame_index = 0
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        try:
            with patch.object(window, "_cancel_active_frame_renders") as cancel_mock:
                with patch.object(window, "_ensure_frame_rendered") as ensure_mock:
                    window._rerender_all_frames()

            cancel_mock.assert_called_once_with(wait=False)
            ensure_mock.assert_called_once_with(0)
            self.assertEqual(window._frame_dirty, [True])
            window.canvas.set_image_state.assert_called_once()
            state = window.canvas.set_image_state.call_args.args[0]
            self.assertEqual(state.feedback.status, "loading")
            self.assertEqual(state.feedback.title, "Rendering Full Frame")
        finally:
            window.deleteLater()

    def test_show_error_exposes_inline_error_details(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        try:
            window.show_error("Open failed", "broken header")

            self.assertEqual(window._latest_error_title, "Open failed")
            self.assertEqual(window._latest_error_detail, "broken header")
            window.app_status_bar.show_error_indicator.assert_called_once_with("Open failed", "broken header")
            window.app_status_bar.showMessage.assert_called_once_with("Open failed: broken header", 5000)
        finally:
            window.deleteLater()

    def test_start_sep_extract_runs_small_roi_without_estimate_prepass(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((20, 30)))
        try:
            with patch("astroview.app.main_window.QThread", _FakeThread):
                with patch("astroview.app.main_window.SEPExtractWorker") as worker_cls:
                    worker_cls.return_value = Mock(
                        moveToThread=Mock(),
                        extraction_ready=_FakeSignal(),
                        estimation_ready=_FakeSignal(),
                        extraction_error=_FakeSignal(),
                        finished=_FakeSignal(),
                        deleteLater=Mock(),
                    )
                    window._start_sep_extract(ROISelection(x0=2, y0=3, width=10, height=8))

            window.app_status_bar.set_activity.assert_called_once_with(
                "Running SEP extraction on 10x8 ROI...",
                progress_value=0,
                progress_max=0,
                cancellable=True,
            )
        finally:
            window.deleteLater()

    def test_start_sep_extract_keeps_estimate_prepass_for_large_roi(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((1200, 1200)))
        try:
            with patch("astroview.app.main_window.QThread", _FakeThread):
                with patch("astroview.app.main_window.SEPExtractWorker") as worker_cls:
                    worker_cls.return_value = Mock(
                        moveToThread=Mock(),
                        extraction_ready=_FakeSignal(),
                        estimation_ready=_FakeSignal(),
                        extraction_error=_FakeSignal(),
                        finished=_FakeSignal(),
                        deleteLater=Mock(),
                    )
                    window._start_sep_extract(ROISelection(x0=0, y0=0, width=1200, height=1200))

            window.app_status_bar.set_activity.assert_called_once_with(
                "Estimating SEP source count on 1200x1200 ROI...",
                progress_value=0,
                progress_max=0,
                cancellable=True,
            )
        finally:
            window.deleteLater()

    def test_handle_sep_extraction_finished_clears_status_activity(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window._active_sep_request_id = 7
        window._status_activity_kind = "sep"
        thread = Mock()
        worker = Mock()
        window._sep_thread = thread
        window._sep_worker = worker
        try:
            window._handle_sep_extraction_finished(7)

            self.assertEqual(window._active_sep_request_id, 7)
            self.assertIs(window._sep_thread, thread)
            window.app_status_bar.clear_activity.assert_not_called()

            window._clear_sep_worker_refs(7, thread, worker)

            window.app_status_bar.clear_activity.assert_called_once_with()
            self.assertIsNone(window._status_activity_kind)
            self.assertIsNone(window._active_sep_request_id)
            self.assertIsNone(window._sep_thread)
        finally:
            window.deleteLater()

    def test_sep_thread_slot_remains_busy_until_thread_finished_cleanup(self) -> None:
        window = MainWindow()
        window._active_sep_request_id = None
        window._sep_thread = Mock()
        try:
            self.assertTrue(window._is_sep_extract_running())
        finally:
            window._sep_thread = None
            window.deleteLater()

    def test_handle_marker_color_changed_reapplies_existing_markers(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.marker_dock = Mock()
        window.marker_dock.color.return_value = QColor("#00ff00")
        window.marker_dock.line_width.return_value = 5
        window.marker_dock.parse_coordinates.return_value = [("pixel", 12.0, 34.0)]
        try:
            with patch.object(window, "_apply_markers") as apply_mock:
                window._handle_marker_color_changed(QColor("#00ff00"))

            apply_mock.assert_called_once_with([("pixel", 12.0, 34.0)])
        finally:
            window.deleteLater()

    def test_handle_source_line_width_changed_updates_canvas_roi_width(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.marker_dock = Mock()
        window.marker_dock.source_color.return_value = QColor("#ff0000")
        window.marker_dock.source_line_width.return_value = 25
        try:
            window._handle_source_line_width_changed(25)

            window.canvas.set_roi_line_width.assert_called_once_with(25)
            window.canvas.set_source_overlay_style.assert_called_once()
        finally:
            window.deleteLater()

    def test_handle_marker_line_width_changed_does_not_touch_roi_overlay(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.marker_dock = Mock()
        window.marker_dock.parse_coordinates.return_value = []
        try:
            window._handle_marker_line_width_changed(7)

            window.canvas.set_roi_line_width.assert_not_called()
            window.canvas.set_source_overlay_style.assert_not_called()
        finally:
            window.deleteLater()

    def test_handle_marker_line_width_changed_reapplies_existing_markers(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.marker_dock = Mock()
        window.marker_dock.color.return_value = QColor("#ff0000")
        window.marker_dock.line_width.return_value = 25
        window.marker_dock.parse_coordinates.return_value = [("pixel", 12.0, 34.0)]
        try:
            with patch.object(window, "_apply_markers") as apply_mock:
                window._handle_marker_line_width_changed(25)

            apply_mock.assert_called_once_with([("pixel", 12.0, 34.0)])
        finally:
            window.deleteLater()

    def test_sync_marker_visual_style_applies_source_defaults_to_canvas(self) -> None:
        window = MainWindow()
        window.canvas = Mock()
        window.marker_dock = Mock()
        window.marker_dock.source_color.return_value = QColor("#123456")
        window.marker_dock.source_line_width.return_value = 5
        try:
            window._sync_marker_visual_style()

            window.canvas.set_roi_color.assert_called_once()
            self.assertEqual(window.canvas.set_roi_color.call_args.args[0].name(), "#123456")
            window.canvas.set_roi_line_width.assert_called_once_with(5)
            window.canvas.set_source_overlay_style.assert_called_once()
            kwargs = window.canvas.set_source_overlay_style.call_args.kwargs
            self.assertEqual(kwargs["color"].name(), "#123456")
            self.assertEqual(kwargs["line_width"], 5)
        finally:
            window.deleteLater()

    def test_activate_frame_enables_sep_panel(self) -> None:
        window = MainWindow()
        window._frames = [FITSData(path="first.fits")]
        window._frame_images = [None]
        window._frame_dirty = [False]
        window.sep_panel = Mock()
        try:
            window._activate_frame(0)

            window.sep_panel.set_panel_state.assert_called_once()
            state = window.sep_panel.set_panel_state.call_args.args[0]
            self.assertTrue(state.enablement.enabled)
        finally:
            window.deleteLater()

    def test_handle_sep_params_changed_updates_service_defaults(self) -> None:
        window = MainWindow()
        params = SEPParameters(thresh=7.5, minarea=12)
        try:
            window.handle_sep_params_changed(params)

            self.assertEqual(window.sep_service.params, params)
        finally:
            window.deleteLater()

    def test_handle_sep_params_changed_marks_existing_catalog_as_stale(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window.source_table_dock = Mock()
        window.current_catalog = SourceCatalog(records=[SourceRecord(source_id=1, x=1.0, y=2.0)])
        params = SEPParameters(thresh=7.5, minarea=12)
        try:
            with patch.object(window, "sync_sep_panel_state") as sync_mock:
                window.handle_sep_params_changed(params)

            self.assertTrue(window._catalog_results_stale)
            window.source_table_dock.set_status_note.assert_called_once_with(
                "Results outdated. Press Ctrl+R to rerun SEP."
            )
            window.app_status_bar.showMessage.assert_called_once()
            sync_mock.assert_called_once_with()
        finally:
            window.deleteLater()

    def test_sync_sep_panel_state_updates_rerun_label_when_catalog_is_stale(self) -> None:
        window = MainWindow()
        window.action_run_sep = Mock()
        window.current_catalog = SourceCatalog(records=[SourceRecord(source_id=1, x=1.0, y=2.0)])
        window._catalog_results_stale = True
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((2, 2)))
        try:
            window.sync_sep_panel_state()

            window.action_run_sep.setText.assert_called_once_with("Rerun SEP Extract")
            tooltip = window.action_run_sep.setToolTip.call_args.args[0]
            self.assertIn("outdated", tooltip.lower())
        finally:
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
