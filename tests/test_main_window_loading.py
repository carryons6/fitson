from __future__ import annotations

import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview import __version__
from astroview.app.contracts import TableColumnSpec
from astroview.app.main_window import MainWindow
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
                    with patch.object(window, "saveGeometry", return_value=QByteArray(b"g")):
                        with patch.object(window, "saveState", return_value=QByteArray(b"s")):
                            with patch("PySide6.QtWidgets.QMainWindow.closeEvent") as super_close_mock:
                                window.closeEvent(event)

            stop_load_mock.assert_called_once_with(wait=True)
            cancel_renders_mock.assert_called_once_with(wait=True)
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

            stop_load_mock.assert_called_once_with(wait=True)
            cancel_renders_mock.assert_called_once_with(wait=True)
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
            self.assertIn(1, window._latest_render_request_by_index)
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

    def test_start_sep_extract_shows_busy_status_activity(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window.fits_service.current_data = FITSData(path="frame.fits", data=np.zeros((20, 30)))
        try:
            with patch("astroview.app.main_window.QThread", _FakeThread):
                with patch("astroview.app.main_window.SEPExtractWorker") as worker_cls:
                    worker_cls.return_value = Mock(
                        moveToThread=Mock(),
                        extraction_ready=_FakeSignal(),
                        extraction_error=_FakeSignal(),
                        finished=_FakeSignal(),
                        deleteLater=Mock(),
                    )
                    window._start_sep_extract(ROISelection(x0=2, y0=3, width=10, height=8))

            window.app_status_bar.set_activity.assert_called_once_with(
                "Running SEP extraction on 10x8 ROI...",
                progress_value=0,
                progress_max=0,
                cancellable=False,
            )
        finally:
            window.deleteLater()

    def test_handle_sep_extraction_finished_clears_status_activity(self) -> None:
        window = MainWindow()
        window.app_status_bar = Mock()
        window._active_sep_request_id = 7
        window._status_activity_kind = "sep"
        try:
            window._handle_sep_extraction_finished(7)

            window.app_status_bar.clear_activity.assert_called_once_with()
            self.assertIsNone(window._status_activity_kind)
        finally:
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
