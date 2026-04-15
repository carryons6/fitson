from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QByteArray, Qt, QThread, QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QImage, QKeySequence, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QToolBar,
    QToolButton,
    QWidget,
)

from .. import APP_NAME, APP_RELEASES_URL, __version__
from ..core import FITSService, OpenFileRequest, PixelSample, ROISelection, SEPService, SourceCatalog
from ..diagnostics import log_current_exception
from .contracts import (
    CanvasImageState,
    CanvasOverlayState,
    ControlEnablementState,
    HeaderViewState,
    RenderControlState,
    SEPPanelState,
    TableViewState,
    TableRowViewModel,
    TableSelectionState,
    ViewFeedbackState,
)
from .catalog_field_dialog import CatalogFieldDialog
from .canvas import ImageCanvas
from .file_load_worker import FITSLoadWorker
from .frame_player_dock import FramePlayerDock
from .frame_bkg_worker import FrameBkgWorker
from .frame_render_worker import FrameRenderWorker
from .header_dialog import HeaderDialog
from .histogram_dock import HistogramDock
from .marker_dock import MarkerDock
from .sep_extract_worker import SEPExtractWorker
from .sep_panel import SEPParamsPanel
from .source_table import SourceTableDock
from .status_bar import AppStatusBar
from .update_check_worker import UpdateCheckResult, UpdateCheckWorker


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level application window skeleton.

    Orchestration contract:
    - Sole coordinator between UI widgets and core services.
    - Pulls domain state from services, then pushes presentation state into views.
    - Keeps all module-to-module calls centralized here.
    """

    PREVIEW_PROFILE_CONFIGS: dict[str, dict[str, int | tuple[int, ...]]] = {
        "Fast": {"load_dimension": 1024, "render_dimensions": (1024,)},
        "Balanced": {"load_dimension": 2048, "render_dimensions": (1024, 2048)},
        "Detailed": {"load_dimension": 3072, "render_dimensions": (1024, 2048, 3072)},
    }
    DEFAULT_PREVIEW_PROFILE = "Balanced"
    SUPPORTED_FITS_SUFFIXES = frozenset({".fits", ".fit", ".fts"})
    WORKSPACE_LAYOUT_VERSION = 4

    def __init__(
        self,
        initial_path: str | None = None,
        initial_hdu: int | None = None,
        *,
        fits_service: FITSService | None = None,
        sep_service: SEPService | None = None,
    ) -> None:
        super().__init__()
        self.initial_path = initial_path
        self.initial_hdu = initial_hdu

        self.canvas: ImageCanvas | None = None
        self.source_table_dock: SourceTableDock | None = None
        self.sep_panel: SEPParamsPanel | None = None
        self.sep_panel_dock: QDockWidget | None = None
        self.marker_dock: MarkerDock | None = None
        self.frame_player_dock: FramePlayerDock | None = None
        self.histogram_dock: HistogramDock | None = None
        self.header_dialog: HeaderDialog | None = None
        self.app_status_bar: AppStatusBar | None = None

        self.menu_file: Any = None
        self.menu_view: Any = None
        self.menu_tools: Any = None
        self.menu_help: Any = None
        self.menu_recent_files: Any = None

        self.main_toolbar: Any = None
        self.stretch_selector: Any = None
        self.interval_selector: Any = None
        self.preview_profile_selector: Any = None
        self.magnifier_spinbox: Any = None

        self.action_open_file: QAction | None = None
        self.action_export_catalog: QAction | None = None
        self.action_show_header: QAction | None = None
        self.action_close_file: QAction | None = None
        self.action_reopen_last_session: QAction | None = None
        self.action_quit: QAction | None = None
        self.action_fit_to_window: QAction | None = None
        self.action_actual_pixels: QAction | None = None
        self.action_zoom_in: QAction | None = None
        self.action_zoom_out: QAction | None = None
        self.action_run_sep: QAction | None = None
        self.action_show_markers: QAction | None = None
        self.action_append_frames: QAction | None = None
        self.action_target_info_fields: QAction | None = None
        self.action_check_updates: QAction | None = None
        self.action_cycle_view_mode: QAction | None = None
        self.action_toggle_magnifier: QAction | None = None
        self.action_reset_workspace_layout: QAction | None = None

        self.fits_service = fits_service or FITSService()
        self.sep_service = sep_service or SEPService()
        self.current_catalog: SourceCatalog | None = None
        self._settings = QSettings("AstroView", "AstroView")
        self._preview_profile_name = self.DEFAULT_PREVIEW_PROFILE
        self._last_auto_interval_name = self.fits_service.current_interval

        from ..core.fits_data import FITSData
        self._frames: list[FITSData] = []
        self._frame_images: list[QImage | None] = []
        self._frame_dirty: list[bool] = []
        self._frame_bkg_cache: list[FITSData | None] = []
        self._frame_residual_cache: list[FITSData | None] = []
        self._view_mode: str = "original"  # "original" | "background" | "residual"
        self._last_title_detail: str | None = None
        self._orientation: tuple[bool, bool, bool] = self._load_orientation_setting()
        self._current_frame_index: int = 0
        self._frame_step_direction: int = 1

        self._load_thread: QThread | None = None
        self._load_worker: FITSLoadWorker | None = None
        self._load_append_mode: bool = False
        self._load_total_count: int = 0
        self._load_completed_count: int = 0
        self._load_error_count: int = 0

        self._render_generation: int = 0
        self._render_request_id: int = 0
        self._render_threads: dict[int, QThread] = {}
        self._render_workers: dict[int, FrameRenderWorker] = {}
        self._render_request_index_by_id: dict[int, int] = {}
        self._latest_render_request_by_index: dict[int, int] = {}
        self._playback_render_queue: list[int] = []
        self._playback_bg_render_ids: set[int] = set()
        self._bkg_threads: dict[int, QThread] = {}
        self._bkg_workers: dict[int, FrameBkgWorker] = {}
        self._sep_thread: QThread | None = None
        self._sep_worker: SEPExtractWorker | None = None
        self._sep_request_id: int = 0
        self._active_sep_request_id: int | None = None
        self._update_check_thread: QThread | None = None
        self._update_check_worker: UpdateCheckWorker | None = None
        self._startup_request_applied = False
        self._status_activity_kind: str | None = None
        self._latest_error_title: str = ""
        self._latest_error_detail: str = ""
        self._catalog_results_stale: bool = False
        self._pending_session_restore_frame_index: int | None = None

    def initialize(self, *, apply_startup_request: bool = True) -> None:
        """High-level bootstrap entry for the window skeleton.

        Intended sequence:
        1. `create_actions()`
        2. `build_ui()`
        3. `connect_signals()`
        4. `reset_view_state()`
        5. `apply_startup_request()`
        """

        self.create_actions()
        self._restore_render_preferences()
        self.build_ui()
        self._restore_workspace_state()
        self.connect_signals()
        self.reset_view_state()
        if apply_startup_request:
            self.apply_startup_request()

    def schedule_startup_request(self) -> None:
        """Defer startup-file opening until the window and event loop are ready."""

        if not self.initial_path or self._startup_request_applied:
            return
        QTimer.singleShot(0, self.apply_startup_request)

    def build_ui(self) -> None:
        """Create menus, toolbars, central widgets, and docks.

        Planned assembly order:
        1. `configure_window_shell()`
        2. `build_central_canvas()`
        3. `build_docks()`
        4. `build_status_bar()`
        5. `build_menu_bar()`
        6. `build_tool_bar()`
        """

        self.configure_window_shell()
        self.build_central_canvas()
        self.build_docks()
        self.build_status_bar()
        self.build_menu_bar()
        self.build_tool_bar()
        self.header_dialog = HeaderDialog(self)

    def create_actions(self) -> None:
        """Create all window actions and shortcuts.

        Planned action groups:
        - file actions
        - view actions
        - tool actions
        - app lifecycle actions
        """

        self.create_file_actions()
        self.create_view_actions()
        self.create_tool_actions()
        self.create_help_actions()

    def connect_signals(self) -> None:
        """Connect UI signals to the window controller methods.

        Main connections to preserve:
        - `ImageCanvas.mouse_moved` -> `update_status_from_cursor`
        - `ImageCanvas.roi_selected` -> `handle_roi_selected`
        - `SourceTableDock.source_clicked` -> `handle_source_clicked`
        - `SEPParamsPanel.params_changed` -> `handle_sep_params_changed`
        """

        self.bind_canvas_signals()
        self.bind_source_table_signals()
        self.bind_sep_panel_signals()
        self.bind_toolbar_signals()
        self.bind_action_triggers()
        self.bind_status_bar_signals()

    def configure_window_shell(self) -> None:
        """Set window title, default size, dock policy, and startup flags."""

        self.setObjectName("main_window")
        self._set_window_title()
        self._apply_initial_window_size()
        self.setAcceptDrops(True)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks
        )

    def _apply_initial_window_size(self) -> None:
        """Size the window to fit the current screen before any saved geometry is restored."""

        default_width = 1440
        default_height = 900
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(default_width, default_height)
            return

        available = screen.availableGeometry()
        width = min(default_width, max(960, available.width() - 80))
        height = min(default_height, max(720, available.height() - 80))
        self.resize(min(width, available.width()), min(height, available.height()))

    def _ensure_window_visible_on_screen(self) -> None:
        """Clamp the restored window geometry so it remains visible on the active screen."""

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        width = min(max(self.width(), 960), available.width())
        height = min(max(self.height(), 720), available.height())
        if width != self.width() or height != self.height():
            self.resize(width, height)

        max_x = max(available.left(), available.right() - width + 1)
        max_y = max(available.top(), available.bottom() - height + 1)
        clamped_x = min(max(self.x(), available.left()), max_x)
        clamped_y = min(max(self.y(), available.top()), max_y)
        if clamped_x != self.x() or clamped_y != self.y():
            self.move(clamped_x, clamped_y)

    def _can_restore_saved_geometry(self) -> bool:
        """Return whether the saved geometry is compatible with the current screen."""

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return True

        saved_name = self._settings.value("window/screen_name", "", type=str)
        saved_width = self._settings.value("window/screen_available_width", 0, type=int)
        saved_height = self._settings.value("window/screen_available_height", 0, type=int)
        if not saved_name or saved_width <= 0 or saved_height <= 0:
            return False

        available = screen.availableGeometry()
        if saved_name != screen.name():
            return False
        if available.width() + 80 < saved_width:
            return False
        if available.height() + 80 < saved_height:
            return False
        return True

    def build_central_canvas(self) -> None:
        """Create the central `ImageCanvas` and register it as the main view."""

        self.canvas = ImageCanvas(self)
        self.setCentralWidget(self.canvas)

    def build_docks(self) -> None:
        """Create dock widgets for the source table, histogram, and SEP panels."""

        self.source_table_dock = SourceTableDock(self)
        self.source_table_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.source_table_dock.setMinimumWidth(360)
        self.sep_panel = SEPParamsPanel(self)
        self.sep_panel_dock = QDockWidget("SEP Params", self)
        self.sep_panel_dock.setObjectName("sep_panel_dock")
        self.sep_panel_dock.setWidget(self.sep_panel)
        self.sep_panel_dock.setMinimumWidth(260)
        self.sep_panel_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.marker_dock = MarkerDock(self)
        self.marker_dock.setMinimumWidth(300)
        self.marker_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.histogram_dock = HistogramDock(self)
        self.histogram_dock.setMinimumWidth(280)
        self.histogram_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.frame_player_dock = FramePlayerDock(self)
        self.frame_player_dock.setMinimumHeight(110)
        self.frame_player_dock.setAllowedAreas(
            Qt.DockWidgetArea.TopDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )

        for dock in (
            self.source_table_dock,
            self.sep_panel_dock,
            self.marker_dock,
            self.histogram_dock,
            self.frame_player_dock,
        ):
            if dock is not None:
                self._install_dock_titlebar(dock)
                self._enable_dock_window_chrome(dock)

        self._apply_default_workspace_layout()
        self.source_table_dock.hide()
        self.sep_panel_dock.hide()
        self.marker_dock.hide()
        self.histogram_dock.hide()
        self.frame_player_dock.hide()

    def _dock_widgets(self) -> list[QDockWidget]:
        """Return all managed dock widgets in a stable order."""

        return [
            dock
            for dock in (
                self.source_table_dock,
                self.sep_panel_dock,
                self.marker_dock,
                self.histogram_dock,
                self.frame_player_dock,
            )
            if dock is not None
        ]

    def _apply_default_workspace_layout(self, *, persist: bool = False) -> None:
        """Apply the default dock arrangement used for a clean workspace."""

        dock_visibility = {dock: dock.isVisible() for dock in self._dock_widgets()}
        for dock in self._dock_widgets():
            dock.setFloating(False)
            self.removeDockWidget(dock)

        if self.histogram_dock is not None:
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.histogram_dock)
        if self.source_table_dock is not None:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.source_table_dock)
            self.source_table_dock.show_cutout_tab()
            self.source_table_dock.update_layout_for_dock_area(Qt.DockWidgetArea.RightDockWidgetArea)
        if self.sep_panel_dock is not None:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.sep_panel_dock)
            if self.source_table_dock is not None:
                self.tabifyDockWidget(self.source_table_dock, self.sep_panel_dock)
        if self.marker_dock is not None:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.marker_dock)
            if self.source_table_dock is not None:
                self.tabifyDockWidget(self.source_table_dock, self.marker_dock)
        if self.frame_player_dock is not None:
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.frame_player_dock)

        if self.source_table_dock is not None and self.histogram_dock is not None:
            self.resizeDocks(
                [self.histogram_dock, self.source_table_dock],
                [280, 420],
                Qt.Orientation.Horizontal,
            )
        if self.source_table_dock is not None:
            self.source_table_dock.show_cutout_tab()
            self.source_table_dock.raise_()

        for dock, visible in dock_visibility.items():
            dock.setVisible(visible)

        if persist:
            self._persist_window_state()

    def _reset_workspace_layout(self) -> None:
        """Restore the managed docks to the default arrangement."""

        self._apply_default_workspace_layout(persist=True)

    def _install_dock_titlebar(self, dock: QDockWidget) -> None:
        """Install a custom title bar with a dock/undock toggle button."""

        bar = QWidget(dock)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 2, 4, 2)
        layout.setSpacing(4)

        title_label = QLabel(dock.windowTitle(), bar)
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label, 1)

        dock_btn = QToolButton(bar)
        dock_btn.setAutoRaise(True)
        dock_btn.setToolTip("停靠 / 浮动")
        dock_btn.setText("⧉")
        dock_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        layout.addWidget(dock_btn)

        close_btn = QToolButton(bar)
        close_btn.setAutoRaise(True)
        close_btn.setToolTip("关闭")
        close_btn.setText("✕")
        close_btn.clicked.connect(dock.close)
        layout.addWidget(close_btn)

        dock.setTitleBarWidget(bar)
        dock.windowTitleChanged.connect(title_label.setText)

        def refresh_dock_button(_floating: bool) -> None:
            dock_btn.setText("⇲" if dock.isFloating() else "⧉")
            dock_btn.setToolTip("停靠回主窗口" if dock.isFloating() else "浮动")

        dock.topLevelChanged.connect(refresh_dock_button)
        refresh_dock_button(dock.isFloating())

    def _enable_dock_window_chrome(self, dock: QDockWidget) -> None:
        """Give a dock full window controls (minimize/maximize/close) when floated."""

        def apply_chrome(floating: bool, _dock: QDockWidget = dock) -> None:
            if not floating:
                return
            _dock.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.CustomizeWindowHint
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMinimizeButtonHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            _dock.show()

        dock.topLevelChanged.connect(apply_chrome)

    def build_status_bar(self) -> None:
        """Create and install the application status bar."""

        self.app_status_bar = AppStatusBar(self)
        self.setStatusBar(self.app_status_bar)

    def build_menu_bar(self) -> None:
        """Create the top-level menus and place actions into them."""

        menu_bar = self.menuBar()
        self.menu_file = menu_bar.addMenu("文件")
        self.menu_view = menu_bar.addMenu("视图")
        self.menu_tools = menu_bar.addMenu("工具")
        self.menu_help = menu_bar.addMenu("帮助")

        if self.action_open_file is not None:
            self.menu_file.addAction(self.action_open_file)
        self.menu_recent_files = self.menu_file.addMenu("Recent Files")
        if self.action_reopen_last_session is not None:
            self.menu_file.addAction(self.action_reopen_last_session)
        if self.action_export_catalog is not None:
            self.menu_file.addAction(self.action_export_catalog)
        if self.action_show_header is not None:
            self.menu_file.addAction(self.action_show_header)
        if self.action_close_file is not None:
            self.menu_file.addAction(self.action_close_file)
        if self.action_append_frames is not None:
            self.menu_file.addAction(self.action_append_frames)
        self.menu_file.addSeparator()
        if self.action_quit is not None:
            self.menu_file.addAction(self.action_quit)
        self._refresh_recent_files_menu()
        if self.action_fit_to_window is not None:
            self.menu_view.addAction(self.action_fit_to_window)
        if self.action_actual_pixels is not None:
            self.menu_view.addAction(self.action_actual_pixels)
        if self.action_zoom_in is not None:
            self.menu_view.addAction(self.action_zoom_in)
        if self.action_zoom_out is not None:
            self.menu_view.addAction(self.action_zoom_out)
        if self.action_cycle_view_mode is not None:
            self.menu_view.addSeparator()
            self.menu_view.addAction(self.action_cycle_view_mode)
        if self.action_toggle_magnifier is not None:
            self.menu_view.addAction(self.action_toggle_magnifier)
        if self.orientation_actions:
            self.menu_view.addSeparator()
            orient_menu = self.menu_view.addMenu("图像方向")
            for act in self.orientation_actions:
                orient_menu.addAction(act)

        if self.action_run_sep is not None:
            self.menu_tools.addAction(self.action_run_sep)
        if self.action_show_markers is not None:
            self.menu_tools.addAction(self.action_show_markers)
        if self.action_target_info_fields is not None:
            self.menu_tools.addAction(self.action_target_info_fields)
        if self.action_check_updates is not None:
            self.menu_help.addAction(self.action_check_updates)

        self.menu_view.addSeparator()
        self._build_theme_menu(self.menu_view)
        self.menu_view.addSeparator()
        if self.action_reset_workspace_layout is not None:
            self.menu_view.addAction(self.action_reset_workspace_layout)
            self.menu_view.addSeparator()
        if self.source_table_dock is not None:
            self.menu_view.addAction(self.source_table_dock.toggleViewAction())
        if self.sep_panel_dock is not None:
            self.menu_view.addAction(self.sep_panel_dock.toggleViewAction())
        if self.marker_dock is not None:
            self.menu_view.addAction(self.marker_dock.toggleViewAction())
        if self.frame_player_dock is not None:
            self.menu_view.addAction(self.frame_player_dock.toggleViewAction())
        if self.histogram_dock is not None:
            self.menu_view.addAction(self.histogram_dock.toggleViewAction())

    def _build_theme_menu(self, parent_menu: Any) -> None:
        """Add a '主题' submenu with Dark/Light options."""
        from .theme import AVAILABLE_THEMES, apply_theme, load_saved_theme, save_theme
        from PySide6.QtWidgets import QApplication

        theme_menu = parent_menu.addMenu("主题")
        group = QActionGroup(self)
        group.setExclusive(True)
        current = load_saved_theme()
        labels = {"dark": "深色", "light": "浅色"}

        def _make_handler(theme_name: str):
            def _handler(checked: bool) -> None:
                if not checked:
                    return
                app = QApplication.instance()
                if app is not None:
                    apply_theme(app, theme_name)
                save_theme(theme_name)
            return _handler

        for name in AVAILABLE_THEMES:
            action = QAction(labels.get(name, name), self)
            action.setCheckable(True)
            action.setChecked(name == current)
            action.triggered.connect(_make_handler(name))
            group.addAction(action)
            theme_menu.addAction(action)

    def build_tool_bar(self) -> None:
        """Create the main toolbar and attach view/render controls."""

        self.main_toolbar = QToolBar("Main Toolbar", self)
        self.main_toolbar.setObjectName("main_toolbar")
        self.addToolBar(self.main_toolbar)

        for action in (
            self.action_open_file,
            self.action_show_header,
            self.action_fit_to_window,
            self.action_actual_pixels,
            self.action_zoom_in,
            self.action_zoom_out,
        ):
            if action is not None:
                self.main_toolbar.addAction(action)

        self.main_toolbar.addSeparator()
        self.main_toolbar.addWidget(QLabel("Stretch:", self))
        if self.stretch_selector is not None:
            self.main_toolbar.addWidget(self.stretch_selector)
        self.main_toolbar.addWidget(QLabel("Interval:", self))
        if self.interval_selector is not None:
            self.main_toolbar.addWidget(self.interval_selector)
        self.main_toolbar.addWidget(QLabel("Preview:", self))
        if self.preview_profile_selector is not None:
            self.main_toolbar.addWidget(self.preview_profile_selector)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addWidget(QLabel("放大镜:", self))
        if self.magnifier_spinbox is not None:
            self.main_toolbar.addWidget(self.magnifier_spinbox)
        self.sync_render_controls()

    def create_file_actions(self) -> None:
        """Define file-oriented actions.

        Planned actions:
        - open file
        - export catalog
        - show header
        - close current file
        - quit application
        """

        self.action_open_file = QAction("Open", self)
        self.action_open_file.setShortcut(QKeySequence.StandardKey.Open)
        self.action_export_catalog = QAction("Export CSV", self)
        self.action_export_catalog.setShortcuts(["Ctrl+E", "Ctrl+Shift+E"])
        self.action_show_header = QAction("Show Header", self)
        self.action_show_header.setShortcut("Ctrl+H")
        self.action_append_frames = QAction("Append Frames...", self)
        self.action_append_frames.setShortcut("Ctrl+Shift+O")
        self.action_close_file = QAction("Close File", self)
        self.action_close_file.setShortcut("Ctrl+W")
        self.action_reopen_last_session = QAction("Reopen Last Session", self)
        self.action_quit = QAction("Quit", self)
        self.action_quit.setShortcut(QKeySequence.StandardKey.Quit)

    def create_view_actions(self) -> None:
        """Define view-oriented actions.

        Planned actions:
        - fit to window
        - actual pixels
        - zoom in
        - zoom out
        """

        self.action_fit_to_window = QAction("Fit", self)
        self.action_fit_to_window.setShortcut("F")
        self.action_actual_pixels = QAction("1:1", self)
        self.action_actual_pixels.setShortcut("1")
        self.action_zoom_in = QAction("Zoom In", self)
        self.action_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.action_zoom_out = QAction("Zoom Out", self)
        self.action_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.action_reset_workspace_layout = QAction("Reset Workspace Layout", self)

        self.action_cycle_view_mode = QAction("切换视图模式", self)
        self.action_cycle_view_mode.setShortcut("Tab")
        self.addAction(self.action_cycle_view_mode)

        self.action_toggle_magnifier = QAction("放大镜", self)
        self.action_toggle_magnifier.setShortcut("F1")
        self.action_toggle_magnifier.setCheckable(True)
        self.addAction(self.action_toggle_magnifier)

        self.orientation_action_group = QActionGroup(self)
        self.orientation_action_group.setExclusive(True)
        self.orientation_actions: list[QAction] = []
        for label, orientation in self._ORIENTATIONS:
            act = QAction(label, self)
            act.setCheckable(True)
            if orientation == self._orientation:
                act.setChecked(True)
            act.triggered.connect(lambda _checked, o=orientation: self._set_orientation(o))
            self.orientation_action_group.addAction(act)
            self.orientation_actions.append(act)

        self.action_prev_frame = QAction("Previous Frame", self)
        self.action_prev_frame.setShortcut("Left")
        self.action_next_frame = QAction("Next Frame", self)
        self.action_next_frame.setShortcut("Right")

    def create_tool_actions(self) -> None:
        """Define tool-oriented actions and non-action controls.

        Planned controls:
        - stretch selector
        - interval selector
        - future MEF/HDU selector entry point
        """

        self.action_run_sep = QAction("SEP Extract", self)
        self.action_run_sep.setShortcut("Ctrl+R")
        self.action_show_markers = QAction("Markers", self)
        self.action_show_markers.setShortcut("Ctrl+M")
        self.action_target_info_fields = QAction("Target Info Fields...", self)

        self.stretch_selector = QComboBox(self)
        self.stretch_selector.setObjectName("stretch_selector")
        self.interval_selector = QComboBox(self)
        self.interval_selector.setObjectName("interval_selector")
        self.preview_profile_selector = QComboBox(self)
        self.preview_profile_selector.setObjectName("preview_profile_selector")

        self.magnifier_spinbox = QSpinBox(self)
        self.magnifier_spinbox.setObjectName("magnifier_spinbox")
        self.magnifier_spinbox.setRange(2, 16)
        self.magnifier_spinbox.setValue(4)
        self.magnifier_spinbox.setSuffix("x")

    def create_help_actions(self) -> None:
        """Define help-oriented actions."""

        self.action_check_updates = QAction("Check for Updates...", self)

    def bind_canvas_signals(self) -> None:
        """Bind `ImageCanvas` signals to window controller methods."""

        if self.canvas is None:
            return
        self.canvas.mouse_moved.connect(self.update_status_from_cursor)
        self.canvas.roi_selected.connect(self.handle_roi_selected)
        self.canvas.source_double_clicked.connect(self.handle_source_clicked)
        self.canvas.zoom_changed.connect(self.handle_zoom_changed)
        self.canvas.files_dropped.connect(self._handle_dropped_paths)

    def bind_source_table_signals(self) -> None:
        """Bind source-table signals to window controller methods."""

        if self.source_table_dock is None:
            return
        self.source_table_dock.source_clicked.connect(self.handle_source_clicked)
        self.source_table_dock.source_hovered.connect(self._handle_source_hovered)
        self.source_table_dock.filter_changed.connect(self._persist_catalog_preferences)
        self.source_table_dock.cutout_mode_changed.connect(lambda _mode: self._update_source_cutout())

    def bind_sep_panel_signals(self) -> None:
        """Bind SEP-parameter panel signals to window controller methods."""

        if self.sep_panel is None:
            return
        self.sep_panel.params_changed.connect(self.handle_sep_params_changed)

    def bind_status_bar_signals(self) -> None:
        """Bind status-bar task affordances back into the controller."""

        if self.app_status_bar is None:
            return
        self.app_status_bar.cancel_requested.connect(self._handle_status_bar_cancel_requested)
        self.app_status_bar.error_details_requested.connect(self._show_latest_error_details)

    def bind_toolbar_signals(self) -> None:
        """Bind toolbar selectors and buttons to render-refresh methods."""

        if self.stretch_selector is not None:
            self.stretch_selector.currentTextChanged.connect(self._handle_stretch_changed)
        if self.interval_selector is not None:
            self.interval_selector.currentTextChanged.connect(self._handle_interval_changed)
        if self.preview_profile_selector is not None:
            self.preview_profile_selector.currentTextChanged.connect(self._handle_preview_profile_changed)
        if self.marker_dock is not None:
            self.marker_dock.radius_spin.valueChanged.connect(self._persist_marker_preferences)
            self.marker_dock.line_width_spin.valueChanged.connect(self._persist_marker_preferences)
            self.marker_dock.color_changed.connect(self._persist_marker_preferences)
        if self.histogram_dock is not None:
            self.histogram_dock.manual_range_applied.connect(self._handle_histogram_manual_range)
            self.histogram_dock.auto_range_requested.connect(self._handle_histogram_auto_range)
            self.histogram_dock.visibilityChanged.connect(self._handle_histogram_visibility_changed)

    def bind_action_triggers(self) -> None:
        """Bind QAction triggers to their command handlers."""

        if self.action_open_file is not None:
            self.action_open_file.triggered.connect(self.open_file)
        if self.action_export_catalog is not None:
            self.action_export_catalog.triggered.connect(self.export_catalog)
        if self.action_show_header is not None:
            self.action_show_header.triggered.connect(self.show_header_dialog)
        if self.action_close_file is not None:
            self.action_close_file.triggered.connect(self.close_current_file)
        if self.action_reopen_last_session is not None:
            self.action_reopen_last_session.triggered.connect(self._reopen_last_session)
        if self.action_quit is not None:
            self.action_quit.triggered.connect(self.close)
        if self.action_fit_to_window is not None and self.canvas is not None:
            self.action_fit_to_window.triggered.connect(self.canvas.fit_to_window)
        if self.action_actual_pixels is not None and self.canvas is not None:
            self.action_actual_pixels.triggered.connect(self.canvas.show_actual_pixels)
        if self.action_zoom_in is not None and self.canvas is not None:
            self.action_zoom_in.triggered.connect(self.canvas.zoom_in)
        if self.action_zoom_out is not None and self.canvas is not None:
            self.action_zoom_out.triggered.connect(self.canvas.zoom_out)
        if self.action_reset_workspace_layout is not None:
            self.action_reset_workspace_layout.triggered.connect(self._reset_workspace_layout)
        if self.action_cycle_view_mode is not None:
            self.action_cycle_view_mode.triggered.connect(self._cycle_view_mode)
        if self.action_toggle_magnifier is not None and self.canvas is not None:
            self.action_toggle_magnifier.triggered.connect(self.canvas.set_magnifier_visible)
        if self.magnifier_spinbox is not None and self.canvas is not None:
            self.magnifier_spinbox.valueChanged.connect(self.canvas.set_magnifier_magnification)
        if self.action_prev_frame is not None:
            self.action_prev_frame.triggered.connect(self._go_prev_frame)
        if self.action_next_frame is not None:
            self.action_next_frame.triggered.connect(self._go_next_frame)
        if self.action_run_sep is not None:
            self.action_run_sep.triggered.connect(self.run_sep_extract)
        if self.action_show_markers is not None:
            self.action_show_markers.triggered.connect(self._show_marker_dock)
        if self.action_target_info_fields is not None:
            self.action_target_info_fields.triggered.connect(self._show_target_info_fields_dialog)
        if self.action_append_frames is not None:
            self.action_append_frames.triggered.connect(self._append_frames)
        if self.action_check_updates is not None:
            self.action_check_updates.triggered.connect(self.check_for_updates)
        if self.marker_dock is not None:
            self.marker_dock.markers_updated.connect(self._apply_markers)
            self.marker_dock.color_changed.connect(self._handle_marker_color_changed)
            self.marker_dock.line_width_changed.connect(self._handle_marker_line_width_changed)
            self._sync_marker_visual_style()
        if self.frame_player_dock is not None:
            self.frame_player_dock.frame_changed.connect(self._switch_frame)
            self.frame_player_dock.playback_started.connect(self._on_playback_started)
            self.frame_player_dock.playback_stopped.connect(self._on_playback_stopped)

    def apply_startup_request(self) -> None:
        """Apply the optional startup file request passed from `main.py`.

        Intended decision point:
        - no startup path: leave window empty
        - startup path provided: build `OpenFileRequest` and forward to `open_file_from_request()`
        """

        if self._startup_request_applied or not self.initial_path:
            return

        self._startup_request_applied = True
        if self.initial_path:
            self.open_file_from_request(
                OpenFileRequest(path=self.initial_path, hdu_index=self.initial_hdu)
            )

    def open_file(self, path: str | None = None, hdu_index: int | None = None) -> None:
        """Open one or more FITS files (replaces existing frames).

        If path is None, a file dialog supporting multi-select is shown.
        """

        if not path:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Open FITS File(s)",
                self._last_open_directory(),
                "FITS Files (*.fits *.fit *.fts);;All Files (*)",
            )
            if not paths:
                return
        else:
            paths = [path]

        self._open_paths(paths, hdu_index=hdu_index, append=False)

    def open_file_from_request(self, request: OpenFileRequest) -> None:
        """Structured wrapper around the public open-file entry point."""

        self.open_file(path=request.path, hdu_index=request.hdu_index)

    def _restore_render_preferences(self) -> None:
        """Load persisted render preferences into the service before UI build."""

        stretch = self._settings.value("render/stretch", self.fits_service.current_stretch, type=str)
        if stretch in self.fits_service.AVAILABLE_STRETCHES:
            self.fits_service.set_stretch(stretch)

        interval = self._settings.value("render/interval", self.fits_service.current_interval, type=str)
        if interval in self.fits_service.AVAILABLE_INTERVALS:
            self.fits_service.set_interval(interval)
            if interval != "Manual":
                self._last_auto_interval_name = interval

        self._last_auto_interval_name = self._settings.value(
            "render/auto_interval",
            self._last_auto_interval_name,
            type=str,
        )

        manual_low = self._settings.value("render/manual_low", None)
        manual_high = self._settings.value("render/manual_high", None)
        try:
            if manual_low is not None and manual_high is not None:
                self.fits_service.set_manual_interval_limits(float(manual_low), float(manual_high))
        except (TypeError, ValueError):
            self.fits_service.clear_manual_interval_limits()

        preview_profile = self._settings.value(
            "render/preview_profile",
            self._preview_profile_name,
            type=str,
        )
        self._preview_profile_name = self._normalize_preview_profile_name(preview_profile)

    def _restore_workspace_state(self) -> None:
        """Restore persisted marker preferences, catalog config, and window layout."""

        if self.marker_dock is not None:
            self.marker_dock.set_radius(self._settings.value("markers/radius", self.marker_dock.radius(), type=float))
            self.marker_dock.set_line_width(
                self._settings.value("markers/line_width", self.marker_dock.line_width(), type=int)
            )
            self.marker_dock.set_color(
                self._settings.value("markers/color", self.marker_dock.color().name(), type=str)
            )
        if self.source_table_dock is not None:
            visible_columns = self._settings.value("catalog/visible_columns", [])
            visible_keys = self._normalize_settings_string_list(visible_columns)
            if visible_keys:
                configured = []
                visible_set = set(visible_keys) | set(self.source_table_dock.MANDATORY_COLUMN_KEYS)
                for column in self.source_table_dock.default_columns():
                    configured.append(
                        column.__class__(
                            key=column.key,
                            title=column.title,
                            width_hint=column.width_hint,
                            visible=column.key in visible_set,
                            alignment=column.alignment,
                        )
                    )
                self.source_table_dock.configure_columns(configured)
            self.source_table_dock.set_filter_text(
                self._settings.value("catalog/filter_text", "", type=str)
            )

        geometry = self._settings.value("window/geometry", QByteArray(), type=QByteArray)
        if geometry and self._can_restore_saved_geometry():
            self.restoreGeometry(geometry)
        else:
            self._apply_initial_window_size()
        self._ensure_window_visible_on_screen()

        state = self._settings.value("window/state", QByteArray(), type=QByteArray)
        layout_version = self._settings.value("window/layout_version", 0, type=int)
        restored_state = False
        if state and layout_version == self.WORKSPACE_LAYOUT_VERSION:
            restored_state = bool(self.restoreState(state))
        if not restored_state:
            self._apply_default_workspace_layout()
        if self.source_table_dock is not None:
            self.source_table_dock.update_layout_for_dock_area(
                self.dockWidgetArea(self.source_table_dock)
            )
        self._ensure_window_visible_on_screen()

        self._refresh_recent_files_menu()
        self.sync_render_controls()
        self._sync_marker_visual_style()
        self._refresh_histogram_view()

    def _persist_render_preferences(self) -> None:
        """Store the current render-control selections."""

        self._settings.setValue("render/stretch", self.fits_service.current_stretch)
        self._settings.setValue("render/interval", self.fits_service.current_interval)
        self._settings.setValue("render/auto_interval", self._last_auto_interval_name)
        manual_limits = self.fits_service.manual_interval_limits
        self._settings.setValue("render/manual_low", None if manual_limits is None else manual_limits[0])
        self._settings.setValue("render/manual_high", None if manual_limits is None else manual_limits[1])
        self._settings.setValue("render/preview_profile", self._preview_profile_name)

    def _normalize_preview_profile_name(self, name: str | None) -> str:
        """Return a valid preview-profile name, falling back to the default."""

        if name in self.PREVIEW_PROFILE_CONFIGS:
            return str(name)
        return self.DEFAULT_PREVIEW_PROFILE

    def _reset_render_controls_for_new_file(self) -> None:
        """Reset display controls to the default Stretch/Interval for newly opened data."""

        self.fits_service.set_stretch(self.fits_service.AVAILABLE_STRETCHES[0])
        self.fits_service.set_interval("ZScale")
        self.fits_service.clear_manual_interval_limits()
        self._last_auto_interval_name = "ZScale"
        self._persist_render_preferences()
        self.sync_render_controls()

    def _preview_profile_config(self) -> dict[str, int | tuple[int, ...]]:
        """Return the active preview pipeline configuration."""

        return self.PREVIEW_PROFILE_CONFIGS[self._preview_profile_name]

    def _preview_load_dimension(self) -> int:
        """Return the max preview dimension used during file loading."""

        return int(self._preview_profile_config()["load_dimension"])

    def _preview_render_dimensions(self) -> tuple[int, ...]:
        """Return the staged preview dimensions used during background rendering."""

        dimensions = self._preview_profile_config()["render_dimensions"]
        return tuple(int(value) for value in dimensions)

    def _persist_marker_preferences(self, *_args: Any) -> None:
        """Store the current marker parameter selections."""

        if self.marker_dock is None:
            return

        self._settings.setValue("markers/radius", self.marker_dock.radius())
        self._settings.setValue("markers/line_width", self.marker_dock.line_width())
        self._settings.setValue("markers/color", self.marker_dock.color().name())

    def _persist_window_state(self) -> None:
        """Store the current window geometry and dock layout."""

        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.setValue("window/layout_version", self.WORKSPACE_LAYOUT_VERSION)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self._settings.setValue("window/screen_name", screen.name())
            self._settings.setValue("window/screen_available_width", available.width())
            self._settings.setValue("window/screen_available_height", available.height())
        self._persist_session_state()

    def _persist_catalog_preferences(self, *_args: Any) -> None:
        """Store catalog column visibility and free-text filter state."""

        if self.source_table_dock is None:
            return

        filter_text = ""
        if hasattr(self.source_table_dock, "filter_text"):
            candidate = self.source_table_dock.filter_text()
            if isinstance(candidate, str):
                filter_text = candidate
        self._settings.setValue("catalog/visible_columns", self._visible_source_table_columns())
        self._settings.setValue("catalog/filter_text", filter_text)

    def _normalize_settings_string_list(self, value: Any) -> list[str]:
        """Normalize QSettings list payloads into plain Python strings."""

        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        return []

    def _recent_files(self) -> list[str]:
        """Return the persisted recent-file list."""

        value = self._settings.value("paths/recent_files", [])
        return self._normalize_settings_string_list(value)

    def _remember_recent_paths(self, paths: list[str]) -> None:
        """Update the recent-files list using newly opened FITS paths."""

        normalized_new = [str(Path(path)) for path in paths if path]
        if not normalized_new:
            return

        existing = self._recent_files()
        merged: list[str] = []
        for path in [*normalized_new, *existing]:
            if path not in merged:
                merged.append(path)
        self._settings.setValue("paths/recent_files", merged[:8])
        self._refresh_recent_files_menu()

    def _refresh_recent_files_menu(self) -> None:
        """Rebuild the Recent Files submenu from persisted settings."""

        if self.menu_recent_files is None:
            return

        self.menu_recent_files.clear()
        recent_files = self._recent_files()
        if not recent_files:
            placeholder = self.menu_recent_files.addAction("No Recent Files")
            placeholder.setEnabled(False)
        else:
            for path in recent_files:
                action = self.menu_recent_files.addAction(Path(path).name)
                action.setToolTip(path)
                action.triggered.connect(lambda _checked=False, p=path: self._open_recent_file(p))

        if self.action_reopen_last_session is not None:
            self.action_reopen_last_session.setEnabled(bool(self._last_session_paths()))

    def _open_recent_file(self, path: str) -> None:
        """Open a path chosen from the Recent Files submenu."""

        if not path:
            return
        self.open_file(path=path)

    def _last_session_paths(self) -> list[str]:
        """Return the last successfully loaded frame-path list."""

        value = self._settings.value("session/last_paths", [])
        return self._normalize_settings_string_list(value)

    def _persist_session_state(self) -> None:
        """Store the last successful frame list and active frame index for reopen."""

        session_paths = [frame.path for frame in self._frames if getattr(frame, "path", None)]
        if not session_paths:
            return

        self._settings.setValue("session/last_paths", session_paths)
        self._settings.setValue("session/current_index", self._current_frame_index)
        self._refresh_recent_files_menu()

    def _reopen_last_session(self) -> None:
        """Reopen the most recently persisted multi-frame session."""

        session_paths = self._last_session_paths()
        if not session_paths:
            self.show_error("Reopen Session", "No previous session is available yet.")
            return

        self._pending_session_restore_frame_index = self._settings.value(
            "session/current_index",
            0,
            type=int,
        )
        self._open_paths(session_paths, append=False)

    def _base_window_title(self) -> str:
        """Return the versioned application title shown in the main window."""

        return f"{APP_NAME} v{__version__}"

    def _set_window_title(self, detail: str | None = None) -> None:
        """Apply the versioned main-window title, optionally with file context."""

        self._last_title_detail = detail
        title = self._base_window_title()
        if detail:
            title = f"{title} - {detail}"
        suffix = self._VIEW_MODE_TITLE_SUFFIX.get(self._view_mode, "")
        if suffix:
            computing = (
                self._view_mode != "original"
                and self._current_frame_index in self._bkg_threads
            )
            if computing:
                suffix = f"{suffix} 计算中..."
            title = f"{title} {suffix}"
        self.setWindowTitle(title)

    def check_for_updates(self) -> None:
        """Start a background check against the configured release source."""

        thread = self._update_check_thread
        if thread is not None and thread.isRunning():
            return

        if self.action_check_updates is not None:
            self.action_check_updates.setEnabled(False)
        if self.app_status_bar is not None:
            self.app_status_bar.showMessage("Checking for updates...")

        self._update_check_thread = QThread(self)
        self._update_check_worker = UpdateCheckWorker(__version__)
        self._update_check_worker.moveToThread(self._update_check_thread)

        self._update_check_thread.started.connect(self._update_check_worker.run)
        self._update_check_worker.result_ready.connect(self._handle_update_check_result)
        self._update_check_worker.finished.connect(self._update_check_thread.quit)
        self._update_check_worker.finished.connect(self._update_check_worker.deleteLater)
        self._update_check_thread.finished.connect(self._clear_update_check_refs)
        self._update_check_thread.finished.connect(self._update_check_thread.deleteLater)
        self._update_check_thread.start()

    def _clear_update_check_refs(self) -> None:
        """Drop references after an update-check worker finishes."""

        self._update_check_thread = None
        self._update_check_worker = None
        if self.action_check_updates is not None:
            self.action_check_updates.setEnabled(True)

    def _handle_update_check_result(self, result: UpdateCheckResult) -> None:
        """Show the outcome of a completed update check."""

        if self.app_status_bar is not None:
            self.app_status_bar.clearMessage()

        if result.status == "update_available":
            latest = result.latest_version or "unknown"
            answer = QMessageBox.question(
                self,
                "Update Available",
                f"A newer version ({latest}) is available.\nCurrent version: {result.current_version}\n\nOpen the releases page now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(result.release_url or APP_RELEASES_URL))
            return

        if result.status == "up_to_date":
            QMessageBox.information(self, "Check for Updates", result.detail)
            return

        if result.status == "unavailable":
            QMessageBox.information(self, "Check for Updates", result.detail)
            return

        QMessageBox.warning(self, "Update Check Failed", result.detail or "Unable to check for updates.")


    def _start_frame_load(
        self,
        paths: list[str],
        *,
        hdu_index: int | None = None,
        append: bool = False,
    ) -> None:
        """Start background loading for one or more FITS files."""

        if not paths:
            return

        self._stop_active_frame_load(wait=True)
        self._load_append_mode = append
        self._load_total_count = len(paths)
        self._load_completed_count = 0
        self._load_error_count = 0

        if not append:
            self.close_current_file()

        self._set_loading_state(True, loaded=0, total=len(paths))

        self._load_thread = QThread(self)
        self._load_worker = FITSLoadWorker(
            paths,
            hdu_index=hdu_index,
            preview_first_frame=not append,
            preview_each_frame=True,
            stretch_name=self.fits_service.current_stretch,
            interval_name=self.fits_service.current_interval,
            preview_max_dimension=self._preview_load_dimension(),
            manual_limits=self.fits_service.manual_interval_limits,
        )
        self._load_worker.moveToThread(self._load_thread)

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.file_loaded.connect(self._handle_loaded_frame)
        self._load_worker.file_error.connect(self._handle_frame_load_error)
        self._load_worker.progress.connect(self._handle_frame_load_progress)
        self._load_worker.finished.connect(self._finish_frame_load)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._clear_load_worker_refs)
        self._load_thread.start()

    def _stop_active_frame_load(self, *, wait: bool = False) -> None:
        """Request cancellation for the active background load, if any."""

        thread = self._load_thread
        if thread is None or not thread.isRunning():
            return

        thread.requestInterruption()
        thread.quit()
        if wait:
            thread.wait()
            self._clear_load_worker_refs()

    def _clear_load_worker_refs(self) -> None:
        """Drop references to the current worker/thread pair after shutdown."""

        self._load_thread = None
        self._load_worker = None

    def _cancel_active_frame_renders(self, *, wait: bool = False) -> None:
        """Request cancellation for all active background frame renders."""

        for thread in list(self._render_threads.values()):
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()

        if wait:
            for thread in list(self._render_threads.values()):
                thread.wait()

    def _handle_frame_render_thread_finished(self, request_id: int) -> None:
        """Drop bookkeeping for a completed frame-render request."""

        was_bg = request_id in self._playback_bg_render_ids
        self._render_threads.pop(request_id, None)
        self._render_workers.pop(request_id, None)
        self._render_request_index_by_id.pop(request_id, None)
        self._playback_bg_render_ids.discard(request_id)
        if was_bg:
            self._pump_playback_render_queue()

    def _cancel_frame_render_request(self, request_id: int, *, wait: bool = False) -> None:
        """Request cancellation for one active frame-render request."""

        thread = self._render_threads.get(request_id)
        if thread is None or not thread.isRunning():
            return

        thread.requestInterruption()
        thread.quit()
        if wait:
            thread.wait()

    def _cancel_stale_frame_renders(self, preferred_index: int, *, wait: bool = False) -> None:
        """Stop active render requests for frames other than the preferred one.

        Playback background renders (full-res cache fills) are preserved.
        """

        for request_id, index in list(self._render_request_index_by_id.items()):
            if index != preferred_index and request_id not in self._playback_bg_render_ids:
                self._cancel_frame_render_request(request_id, wait=wait)

    def _has_active_render_for_index(self, index: int) -> bool:
        """Return whether the given frame currently has a running render request."""

        request_id = self._latest_render_request_by_index.get(index)
        if request_id is None:
            return False
        thread = self._render_threads.get(request_id)
        return thread is not None and thread.isRunning()

    def _render_data_for_index(self, index: int) -> Any:
        """Return cached FITSData for the current view mode, else the original.

        If a background/residual variant is needed but not yet cached, the
        caller is expected to dispatch a `FrameBkgWorker`; this method itself
        never blocks the UI thread on SEP computation.
        """

        original = self._frames[index]
        if self._view_mode == "original" or original.data is None:
            return original
        if self._view_mode == "background":
            cached = self._frame_bkg_cache[index] if index < len(self._frame_bkg_cache) else None
        else:
            cached = self._frame_residual_cache[index] if index < len(self._frame_residual_cache) else None
        return cached if cached is not None else original

    def _frame_bkg_cached(self, index: int) -> bool:
        """Whether the cache slot needed for the current view mode is populated."""

        if self._view_mode == "original":
            return True
        if not (0 <= index < len(self._frames)):
            return True
        if self._view_mode == "background":
            return self._frame_bkg_cache[index] is not None
        return self._frame_residual_cache[index] is not None

    def _dispatch_bkg_worker(self, index: int) -> None:
        """Compute background/residual for `index` off the UI thread."""

        if not (0 <= index < len(self._frames)):
            return
        if index in self._bkg_threads:
            return  # already in flight
        original = self._frames[index]
        if original.data is None:
            return

        thread = QThread(self)
        worker = FrameBkgWorker(
            frame_index=index,
            generation=self._render_generation,
            data=original.data,
            sep_service=self.sep_service,
            params=self.sep_service.params,
        )
        worker.moveToThread(thread)
        self._bkg_threads[index] = thread
        self._bkg_workers[index] = worker

        if index == self._current_frame_index:
            if self.app_status_bar is not None:
                self.app_status_bar.showMessage("正在计算背景...", 0)
            self._set_window_title(self._last_title_detail)

        thread.started.connect(worker.run)
        worker.bkg_ready.connect(self._handle_bkg_ready)
        worker.bkg_error.connect(self._handle_bkg_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda idx=index: self._handle_bkg_thread_finished(idx))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _handle_bkg_ready(self, index: int, generation: int, bkg: Any, residual: Any) -> None:
        if generation != self._render_generation:
            return
        if not (0 <= index < len(self._frames)):
            return
        import dataclasses
        original = self._frames[index]
        self._frame_bkg_cache[index] = dataclasses.replace(original, data=bkg)
        self._frame_residual_cache[index] = dataclasses.replace(original, data=residual)
        if self._view_mode != "original":
            self._frame_dirty[index] = True
            self._schedule_frame_render(index)
        if index == self._current_frame_index and self.source_table_dock is not None:
            mode = self.source_table_dock.current_cutout_mode()
            if mode in (
                SourceTableDock.CUTOUT_MODE_BACKGROUND,
                SourceTableDock.CUTOUT_MODE_RESIDUAL,
            ):
                self._update_source_cutout()

    def _handle_bkg_error(self, index: int, generation: int, detail: str) -> None:
        logger.error("Background computation failed for frame %d: %s", index, detail)

    def _handle_bkg_thread_finished(self, index: int) -> None:
        self._bkg_threads.pop(index, None)
        self._bkg_workers.pop(index, None)
        if index == self._current_frame_index:
            self._set_window_title(self._last_title_detail)
            if not self._bkg_threads and self.app_status_bar is not None:
                self.app_status_bar.clearMessage()

    def _cancel_bkg_workers(self, wait: bool = False) -> None:
        for thread in list(self._bkg_threads.values()):
            thread.requestInterruption()
            thread.quit()
            if wait:
                thread.wait()
        if wait:
            self._bkg_threads.clear()
            self._bkg_workers.clear()

    def _invalidate_bkg_caches(self, indices: list[int] | None = None) -> None:
        """Drop cached background/residual images.

        Call after anything that changes the underlying pixel data (HDU swap,
        frame reload) or background-extraction parameters. If the current view
        mode depends on the cache, the affected frames are re-rendered.
        """

        if indices is None:
            for i in range(len(self._frame_bkg_cache)):
                self._frame_bkg_cache[i] = None
            for i in range(len(self._frame_residual_cache)):
                self._frame_residual_cache[i] = None
            target_indices = list(range(len(self._frames)))
        else:
            target_indices = []
            for i in indices:
                if 0 <= i < len(self._frame_bkg_cache):
                    self._frame_bkg_cache[i] = None
                if 0 <= i < len(self._frame_residual_cache):
                    self._frame_residual_cache[i] = None
                if 0 <= i < len(self._frames):
                    target_indices.append(i)

        if self._view_mode == "original" or not target_indices:
            return
        self._render_generation += 1
        self._cancel_active_frame_renders(wait=False)
        self._cancel_bkg_workers(wait=False)
        self._render_request_index_by_id.clear()
        self._latest_render_request_by_index.clear()
        for i in target_indices:
            self._frame_dirty[i] = True
        self._sync_current_canvas_image_state()
        if self._current_frame_index in target_indices:
            self._ensure_frame_rendered(self._current_frame_index)

    _VIEW_MODE_ORDER = ("original", "background", "residual")
    _VIEW_MODE_LABELS = {
        "original": "原始图像",
        "background": "背景图 (BKG)",
        "residual": "原图 - 背景 (Residual)",
    }
    _VIEW_MODE_TITLE_SUFFIX = {
        "original": "",
        "background": "[BKG]",
        "residual": "[RESIDUAL]",
    }

    _ORIENTATIONS: list[tuple[str, tuple[bool, bool, bool]]] = [
        ("原始 (Identity)", (False, False, False)),
        ("水平翻转", (True, False, False)),
        ("垂直翻转", (False, True, False)),
        ("旋转 180°", (True, True, False)),
        ("转置", (False, False, True)),
        ("旋转 90° CW", (False, True, True)),
        ("旋转 90° CCW", (True, False, True)),
        ("反对角转置", (True, True, True)),
    ]

    _ORIENTATION_SETTINGS_KEY = "view/orientation"

    def _load_orientation_setting(self) -> tuple[bool, bool, bool]:
        raw = self._settings.value(self._ORIENTATION_SETTINGS_KEY, "0,0,0")
        try:
            parts = [p.strip() for p in str(raw).split(",")]
            if len(parts) != 3:
                return (False, False, False)
            return (parts[0] == "1", parts[1] == "1", parts[2] == "1")
        except Exception:
            return (False, False, False)

    def _save_orientation_setting(self) -> None:
        fh, fv, tr = self._orientation
        self._settings.setValue(
            self._ORIENTATION_SETTINGS_KEY,
            f"{int(fh)},{int(fv)},{int(tr)}",
        )

    def _orient_point(self, x: float, y: float, w: int, h: int) -> tuple[float, float]:
        """Map original-image coords (within w×h) to displayed coords."""
        fh, fv, tr = self._orientation
        if tr:
            x, y = y, x
            w, h = h, w
        if fh:
            x = (w - 1) - x
        if fv:
            y = (h - 1) - y
        return x, y

    def _unorient_point(self, x: float, y: float, w: int, h: int) -> tuple[float, float]:
        """Map displayed coords back to original (w, h are ORIGINAL dims)."""
        fh, fv, tr = self._orientation
        wd, hd = (h, w) if tr else (w, h)
        if fh:
            x = (wd - 1) - x
        if fv:
            y = (hd - 1) - y
        if tr:
            x, y = y, x
        return x, y

    def _orient_qimage(self, image: QImage) -> QImage:
        """Apply the current orientation to a QImage. Returns a transformed copy."""

        if not isinstance(image, QImage) or self._orientation == (False, False, False):
            return image
        fh, fv, tr = self._orientation
        out = image
        if tr:
            t = QTransform(0, 1, 1, 0, 0, 0)  # swap x,y
            out = out.transformed(t)
        if fh:
            if hasattr(out, "flipped"):
                out = out.flipped(Qt.Orientation.Horizontal)
            else:
                out = out.mirrored(True, False)
        if fv:
            if hasattr(out, "flipped"):
                out = out.flipped(Qt.Orientation.Vertical)
            else:
                out = out.mirrored(False, True)
        return out

    def _axis_directions(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Return displayed-frame direction vectors for original +X and +Y axes."""

        fh, fv, tr = self._orientation
        x_axis = [1.0, 0.0]
        y_axis = [0.0, 1.0]
        if tr:
            x_axis = [x_axis[1], x_axis[0]]
            y_axis = [y_axis[1], y_axis[0]]
        if fh:
            x_axis[0] = -x_axis[0]
            y_axis[0] = -y_axis[0]
        if fv:
            x_axis[1] = -x_axis[1]
            y_axis[1] = -y_axis[1]
        return tuple(x_axis), tuple(y_axis)

    def _current_original_shape(self) -> tuple[int, int] | None:
        data = self.fits_service.current_data
        if data is None or data.data is None:
            return None
        h, w = data.data.shape[:2]
        return w, h

    def _set_orientation(self, orientation: tuple[bool, bool, bool]) -> None:
        if orientation == self._orientation:
            return
        self._orientation = orientation
        self._save_orientation_setting()
        for act, (_, o) in zip(getattr(self, "orientation_actions", []), self._ORIENTATIONS):
            act.setChecked(o == orientation)
        if self.canvas is not None:
            x_axis, y_axis = self._axis_directions()
            self.canvas.compass.set_axes(x_axis, y_axis)
            shape = self._current_original_shape()
            if shape is not None:
                w, h = shape
                self.canvas.set_source_position_transform(
                    lambda px, py, w=w, h=h: self._orient_point(px, py, w, h)
                )
            else:
                self.canvas.set_source_position_transform(None)
        self._show_current_frame_image()

    _VIEW_MODE_BADGE = {
        "original": "",
        "background": "BKG",
        "residual": "RESIDUAL",
    }

    def _cycle_view_mode(self) -> None:
        """TAB: cycle through original → background → residual → original."""

        if not self._frames:
            if self.app_status_bar is not None:
                self.app_status_bar.showMessage("未加载图像", 2000)
            return
        order = self._VIEW_MODE_ORDER
        idx = order.index(self._view_mode)
        self._set_view_mode(order[(idx + 1) % len(order)])

    def _set_view_mode(self, mode: str) -> None:
        if mode == self._view_mode:
            return
        self._view_mode = mode
        if self.app_status_bar is not None:
            self.app_status_bar.set_view_mode_label(self._VIEW_MODE_BADGE.get(mode, ""))
        self._set_window_title(self._last_title_detail)
        if self.app_status_bar is not None:
            self.app_status_bar.showMessage(
                f"显示：{self._VIEW_MODE_LABELS[mode]}", 2000
            )
        self._rerender_all_frames()

    def _is_playback_active(self) -> bool:
        """Return whether the frame player is currently playing."""
        return self.frame_player_dock is not None and self.frame_player_dock.is_playing()

    def _on_playback_started(self) -> None:
        """Begin background full-resolution renders for all dirty frames."""
        self._build_playback_render_queue()
        self._pump_playback_render_queue()

    def _on_playback_stopped(self) -> None:
        """Trigger a full render for the current frame when playback stops."""
        self._playback_render_queue.clear()
        self._playback_bg_render_ids.clear()
        idx = self._current_frame_index
        if 0 <= idx < len(self._frame_dirty) and self._frame_dirty[idx]:
            self._schedule_frame_render(idx)

    def _build_playback_render_queue(self) -> None:
        """Build ordered queue of dirty frames to render during playback.

        Frames are ordered starting after the current frame so that upcoming
        frames in the playback sequence are rendered first.
        """
        count = len(self._frames)
        if count == 0:
            self._playback_render_queue = []
            return
        start = self._current_frame_index
        queue = []
        for offset in range(count):
            idx = (start + offset + 1) % count
            if self._frame_dirty[idx]:
                queue.append(idx)
        self._playback_render_queue = queue

    def _pump_playback_render_queue(self) -> None:
        """Start the next background full render from the playback queue."""
        if not self._is_playback_active():
            return

        # Wait until no background render is in flight.
        for rid in list(self._playback_bg_render_ids):
            thread = self._render_threads.get(rid)
            if thread is not None and thread.isRunning():
                return

        while self._playback_render_queue:
            idx = self._playback_render_queue.pop(0)
            if 0 <= idx < len(self._frame_dirty) and self._frame_dirty[idx]:
                self._schedule_frame_render(idx, playback_bg=True)
                return
        # Queue exhausted — nothing left to do.

    def _schedule_frame_render(self, index: int, *, playback_bg: bool = False) -> None:
        """Render the requested frame in the background."""

        if index < 0 or index >= len(self._frames):
            return
        if not self._frame_dirty[index]:
            return
        if not self._frame_bkg_cached(index):
            self._dispatch_bkg_worker(index)
            return

        playing = self._is_playback_active()

        if not playback_bg:
            # During playback, skip rendering if a preview image is already cached.
            if playing and self._frame_images[index] is not None:
                return
            if index != self._current_frame_index and self._has_active_render_for_index(self._current_frame_index):
                return

        request_id = self._latest_render_request_by_index.get(index)
        if request_id is not None:
            thread = self._render_threads.get(request_id)
            if thread is not None and thread.isRunning():
                return

        if not playback_bg and index == self._current_frame_index:
            self._cancel_stale_frame_renders(index)

        self._render_request_id += 1
        request_id = self._render_request_id
        self._latest_render_request_by_index[index] = request_id
        self._render_request_index_by_id[request_id] = index
        if playback_bg:
            self._playback_bg_render_ids.add(request_id)

        use_preview_only = playing and not playback_bg

        thread = QThread(self)
        worker = FrameRenderWorker(
            request_id=request_id,
            generation=self._render_generation,
            frame_index=index,
            data=self._render_data_for_index(index),
            stretch_name=self.fits_service.current_stretch,
            interval_name=self.fits_service.current_interval,
            preview_dimensions=self._preview_render_dimensions(),
            manual_limits=self.fits_service.manual_interval_limits,
            preview_only=use_preview_only,
        )
        worker.moveToThread(thread)
        self._render_workers[request_id] = worker

        thread.started.connect(worker.run)
        worker.preview_ready.connect(self._handle_frame_preview_rendered)
        worker.render_ready.connect(self._handle_frame_rendered)
        worker.render_error.connect(self._handle_frame_render_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda rid=request_id: self._handle_frame_render_thread_finished(rid))
        thread.finished.connect(thread.deleteLater)

        self._render_threads[request_id] = thread
        thread.start()

    def _should_accept_render_result(self, request_id: int, generation: int, index: int) -> bool:
        """Return whether a background render result still matches current state."""

        if generation != self._render_generation:
            return False
        if index < 0 or index >= len(self._frames):
            return False
        return self._latest_render_request_by_index.get(index) == request_id

    def _handle_frame_preview_rendered(
        self,
        request_id: int,
        generation: int,
        index: int,
        image_u8: Any,
    ) -> None:
        """Apply a quick preview render for a frame if it is still current."""

        if not self._should_accept_render_result(request_id, generation, index):
            return

        self._frame_images[index] = self._qimage_from_u8(image_u8)
        if self._current_frame_index == index:
            self._show_current_frame_image()
            self._sync_current_canvas_image_state()
            if self.canvas is not None and len(self._frames) == 1:
                self.canvas.show_actual_pixels()
                self.canvas.centerOn(self.canvas._pixmap_item)

    def _handle_frame_rendered(
        self,
        request_id: int,
        generation: int,
        index: int,
        image_u8: Any,
    ) -> None:
        """Apply a full-resolution render result for a frame if it is still current."""

        if not self._should_accept_render_result(request_id, generation, index):
            return

        self._frame_images[index] = self._qimage_from_u8(image_u8)
        self._frame_dirty[index] = False
        if self._current_frame_index == index:
            self._show_current_frame_image()
            self._sync_current_canvas_image_state()
            self._prewarm_adjacent_frame()

    def _handle_frame_render_error(
        self,
        request_id: int,
        generation: int,
        index: int,
        detail: str,
    ) -> None:
        """Report a frame-render failure if it still matches the current state."""

        if not self._should_accept_render_result(request_id, generation, index):
            return
        self._frame_dirty[index] = False
        if self._current_frame_index == index:
            self._sync_current_canvas_image_state()
        self.show_error("Render failed", detail)

    def _set_loading_state(
        self,
        is_loading: bool,
        *,
        loaded: int = 0,
        total: int = 0,
        current_path: str | None = None,
    ) -> None:
        """Update action enablement and visible status-bar progress for file loading."""

        for action in (self.action_open_file, self.action_append_frames, self.action_close_file):
            if action is not None:
                action.setEnabled(not is_loading)

        if self.app_status_bar is None:
            return

        if not is_loading:
            self._clear_status_activity(kind="load")
            self.app_status_bar.clearMessage()
            return

        if total <= 0:
            self._set_status_activity(
                kind="load",
                text="Loading FITS files...",
                progress_value=0,
                progress_max=0,
                cancellable=True,
            )
            return

        filename = ""
        if current_path:
            filename = Path(current_path).name
        if filename:
            text = f"Loading FITS {loaded}/{total}: {filename}"
        else:
            text = f"Loading FITS {loaded}/{total}..."
        self._set_status_activity(
            kind="load",
            text=text,
            progress_value=loaded,
            progress_max=total,
            cancellable=True,
        )

    def _set_status_activity(
        self,
        *,
        kind: str,
        text: str,
        progress_value: int | None = None,
        progress_max: int | None = None,
        cancellable: bool = False,
    ) -> None:
        """Push a persistent task indicator into the status bar."""

        self._status_activity_kind = kind
        if self.app_status_bar is not None:
            self.app_status_bar.set_activity(
                text,
                progress_value=progress_value,
                progress_max=progress_max,
                cancellable=cancellable,
            )

    def _clear_status_activity(self, *, kind: str | None = None) -> None:
        """Hide the status-bar task indicator when the active kind matches."""

        if kind is not None and self._status_activity_kind not in (None, kind):
            return
        self._status_activity_kind = None
        if self.app_status_bar is not None:
            self.app_status_bar.clear_activity()

    def _clear_latest_error(self) -> None:
        """Drop the currently stored inline error summary."""

        self._latest_error_title = ""
        self._latest_error_detail = ""
        if self.app_status_bar is not None:
            self.app_status_bar.clear_error_indicator()

    def _handle_status_bar_cancel_requested(self) -> None:
        """Cancel the currently exposed long-running task when supported."""

        if self._status_activity_kind == "load":
            self._stop_active_frame_load(wait=False)
            self._set_status_activity(
                kind="load",
                text="Cancelling FITS load...",
                progress_value=self._load_completed_count,
                progress_max=self._load_total_count,
                cancellable=False,
            )

    def _show_latest_error_details(self) -> None:
        """Open a dialog with the most recently stored error detail."""

        if not self._latest_error_title and not self._latest_error_detail:
            return
        QMessageBox.warning(
            self,
            self._latest_error_title or "Error",
            self._latest_error_detail or self._latest_error_title,
        )

    def _handle_loaded_frame(self, data: Any, preview_image_u8: Any = None) -> None:
        """Accept one loaded FITS frame from the background worker."""

        self._frames.append(data)
        if preview_image_u8 is not None:
            self._frame_images.append(self._qimage_from_u8(preview_image_u8))
        else:
            self._frame_images.append(None)
        self._frame_dirty.append(True)
        self._frame_bkg_cache.append(None)
        self._frame_residual_cache.append(None)

        if len(self._frames) == 1:
            self._activate_frame(0)

        self._sync_frame_player()
        if self.app_status_bar is not None and self._frames:
            self.app_status_bar.set_frame_info(self._current_frame_index, len(self._frames))

    def _handle_frame_load_error(self, path: str, detail: str) -> None:
        """Receive a file-load failure from the background worker."""

        self._load_error_count += 1
        title = "Append failed" if self._load_append_mode else "Open failed"
        self.show_error(title, f"{path}: {detail}")

    def _handle_frame_load_progress(self, completed: int, total: int, path: str) -> None:
        """Refresh progress text as the background worker advances."""

        self._load_completed_count = completed
        self._load_total_count = total
        self._set_loading_state(True, loaded=completed, total=total, current_path=path)

    def _finish_frame_load(self) -> None:
        """Finalize UI state after the background load finishes."""

        self._set_loading_state(False)
        success_count = max(0, self._load_total_count - self._load_error_count)

        if not self._frames:
            self._pending_session_restore_frame_index = None
            if self.app_status_bar is not None:
                self.app_status_bar.showMessage("No FITS files were loaded.", 5000)
            return

        if self.app_status_bar is not None:
            if self._load_error_count:
                self.app_status_bar.showMessage(
                    f"Loaded {success_count}/{self._load_total_count} FITS files ({self._load_error_count} failed).",
                    5000,
                )
            else:
                self.app_status_bar.showMessage(
                    f"Loaded {success_count} FITS file{'s' if success_count != 1 else ''}.",
                    3000,
                )
        self._persist_session_state()
        if self._pending_session_restore_frame_index is not None and len(self._frames) > 1:
            restore_index = max(0, min(self._pending_session_restore_frame_index, len(self._frames) - 1))
            if restore_index != self._current_frame_index:
                self._switch_frame(restore_index)
        self._pending_session_restore_frame_index = None

    def _open_paths(
        self,
        paths: list[str],
        *,
        hdu_index: int | None = None,
        append: bool = False,
    ) -> None:
        """Open or append a set of already-selected FITS paths."""

        if not paths:
            return

        self._remember_open_directory(paths)
        self._remember_recent_paths(paths)
        self._clear_latest_error()
        if not append:
            self._reset_render_controls_for_new_file()
        self._start_frame_load(paths, hdu_index=hdu_index, append=append)

    def _supported_fits_paths(self, paths: list[str]) -> list[str]:
        """Return only local FITS-like paths supported by AstroView."""

        supported: list[str] = []
        for path in paths:
            suffix = Path(path).suffix.lower()
            if suffix in self.SUPPORTED_FITS_SUFFIXES:
                supported.append(path)
        return supported

    def _handle_dropped_paths(self, paths: list[str]) -> None:
        """Handle local file paths dropped onto the main window."""

        fits_paths = self._supported_fits_paths(paths)
        if not fits_paths:
            self.show_error("Open failed", "Drop one or more FITS files (.fits, .fit, .fts).")
            return
        self._open_paths(fits_paths, append=False)

    def dragEnterEvent(self, event: Any) -> None:
        """Accept drag-enter events that include at least one FITS path."""

        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            event.ignore()
            return

        paths = [
            url.toLocalFile()
            for url in mime_data.urls()
            if hasattr(url, "isLocalFile") and url.isLocalFile()
        ]
        if self._supported_fits_paths(paths):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: Any) -> None:
        """Open dropped FITS paths directly from the shell or file manager."""

        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            event.ignore()
            return

        paths = [
            url.toLocalFile()
            for url in mime_data.urls()
            if hasattr(url, "isLocalFile") and url.isLocalFile()
        ]
        self._handle_dropped_paths(paths)
        event.acceptProposedAction()

    def close_current_file(self) -> None:
        """Close the current FITS file and reset the window state.

        Main flow:
        `MainWindow.close_current_file()` -> `FITSService.close_file()`
        -> clear canvas, table, dialog state, and status bar.
        """

        self._stop_active_frame_load(wait=True)
        self._playback_render_queue.clear()
        self._playback_bg_render_ids.clear()
        self._cancel_active_frame_renders(wait=True)
        self._cancel_bkg_workers(wait=True)
        self._cancel_active_sep_extract(wait=True)
        self._render_generation += 1
        self._render_request_index_by_id.clear()
        self._latest_render_request_by_index.clear()
        self._render_workers.clear()
        self._clear_status_activity()
        self._clear_latest_error()
        self.fits_service.close_file()
        self.current_catalog = None
        self._catalog_results_stale = False
        self._frames.clear()
        self._frame_images.clear()
        self._frame_dirty.clear()
        self._frame_bkg_cache.clear()
        self._frame_residual_cache.clear()
        if self._view_mode != "original":
            self._view_mode = "original"
            if self.app_status_bar is not None:
                self.app_status_bar.set_view_mode_label("")
        self._current_frame_index = 0
        self._set_window_title()

        if self.canvas is not None:
            self.canvas.clear_image()
            self.canvas.clear_sources()
            self.canvas.clear_markers()
            self.canvas.set_image_state(self.build_canvas_image_state())
            self.canvas.set_overlay_state(self.build_canvas_overlay_state())
        if self.source_table_dock is not None:
            self.source_table_dock.clear_catalog()
            self.source_table_dock.set_status_note("")
            self.source_table_dock.set_view_state(self.build_table_view_state())
        if self.header_dialog is not None:
            self.header_dialog.clear()
        if self.app_status_bar is not None:
            self.app_status_bar.clear_data()
        if self.frame_player_dock is not None:
            self.frame_player_dock.set_frame_count(0)
            self.frame_player_dock.hide()
        if self.histogram_dock is not None:
            self.histogram_dock.clear_histogram()
        self.sync_sep_panel_state()
        self.sync_render_controls()

    def refresh_image(self) -> None:
        """Re-render and refresh the central image view.

        Main flow:
        `MainWindow.refresh_image()` -> `FITSService.render()` -> `ImageCanvas.set_image()`.
        """

        result = self.fits_service.render()

        if self.canvas is not None:
            self.canvas.clear_image()
            self.canvas.clear_sources()
            if result.image_u8 is not None:
                h, w = result.height, result.width
                qimage = QImage(result.image_u8.data, w, h, w, QImage.Format.Format_Grayscale8)
                self.canvas.set_image(qimage.copy())
            self.canvas.set_image_state(self.build_canvas_image_state())
            self.canvas.set_overlay_state(self.build_canvas_overlay_state())

        if self.source_table_dock is not None:
            self.source_table_dock.clear_catalog()
            self.source_table_dock.set_view_state(self.build_table_view_state())
        if self.header_dialog is not None:
            self.header_dialog.clear()
            self.header_dialog.set_view_state(self.build_header_view_state())
        self.sync_sep_panel_state()
        self._refresh_histogram_view()
        if self.app_status_bar is not None:
            self.app_status_bar.clear_data()
        self.sync_render_controls()

    def sync_sep_panel_state(self) -> None:
        """Push current enablement/feedback state into the SEP parameter panel."""

        if self.sep_panel is not None:
            self.sep_panel.set_panel_state(self.build_sep_panel_state())
        if self.action_run_sep is not None:
            enablement = self.build_sep_enablement_state()
            self.action_run_sep.setEnabled(enablement.enabled)
            stale_hint = (
                " Current source results are outdated; rerun SEP to refresh them."
                if self._catalog_results_stale and self.current_catalog is not None
                else ""
            )
            self.action_run_sep.setText("Rerun SEP Extract" if stale_hint else "SEP Extract")
            self.action_run_sep.setToolTip(f"{enablement.reason}{stale_hint}".strip())

    def sync_render_controls(self) -> None:
        """Push service-side render configuration into toolbar controls."""

        state = self.build_render_control_state()
        if self.stretch_selector is not None:
            self.stretch_selector.blockSignals(True)
            self.stretch_selector.clear()
            self.stretch_selector.addItems(list(state.available_stretches))
            self.stretch_selector.setCurrentText(state.current_stretch)
            self.stretch_selector.setEnabled(state.enabled)
            self.stretch_selector.setToolTip(state.disabled_reason)
            self.stretch_selector.blockSignals(False)
        if self.interval_selector is not None:
            self.interval_selector.blockSignals(True)
            self.interval_selector.clear()
            self.interval_selector.addItems(list(state.available_intervals))
            self.interval_selector.setCurrentText(state.current_interval)
            self.interval_selector.setEnabled(state.enabled)
            self.interval_selector.setToolTip(state.disabled_reason)
            self.interval_selector.blockSignals(False)
        if self.preview_profile_selector is not None:
            self.preview_profile_selector.blockSignals(True)
            self.preview_profile_selector.clear()
            self.preview_profile_selector.addItems(list(state.available_preview_profiles))
            self.preview_profile_selector.setCurrentText(state.current_preview_profile)
            self.preview_profile_selector.setEnabled(True)
            self.preview_profile_selector.setToolTip(
                "Controls how aggressively AstroView renders preview stages before the full frame."
            )
            self.preview_profile_selector.blockSignals(False)
        if self.action_export_catalog is not None:
            self.action_export_catalog.setEnabled(self.current_catalog is not None and len(self.current_catalog) > 0)

    def build_render_control_state(self) -> RenderControlState:
        """Construct the toolbar render-control state from the FITS service."""

        has_data = self.fits_service.current_data is not None
        return RenderControlState(
            available_stretches=tuple(self.fits_service.AVAILABLE_STRETCHES),
            available_intervals=tuple(self.fits_service.AVAILABLE_INTERVALS),
            available_preview_profiles=tuple(self.PREVIEW_PROFILE_CONFIGS),
            current_stretch=self.fits_service.current_stretch,
            current_interval=self.fits_service.current_interval,
            current_preview_profile=self._preview_profile_name,
            enabled=has_data,
            disabled_reason="" if has_data else "No FITS image is currently loaded.",
        )

    def sync_catalog_views(self) -> None:
        """Push the current source catalog into all dependent views."""

        rows = self.build_table_rows(self.current_catalog)
        if self.source_table_dock is not None:
            if self.current_catalog is not None:
                self.source_table_dock.populate(self.current_catalog)
            self.source_table_dock.set_row_view_models(rows)
            self.source_table_dock.set_status_note(self._catalog_status_note())
            self.source_table_dock.set_view_state(self.build_table_view_state())
            if self.current_catalog is not None and len(self.current_catalog) > 0:
                self.source_table_dock.show()
            else:
                self.source_table_dock.set_status_note("")
                self.source_table_dock.clear_cutout_image()
        if self.canvas is not None:
            self.canvas.draw_sources(self.current_catalog)
            self.canvas.set_overlay_state(self.build_canvas_overlay_state())
        self.sync_render_controls()

    def _catalog_status_note(self) -> str:
        """Return the current source-table status note shown beside the row summary."""

        if self._catalog_results_stale and self.current_catalog is not None and len(self.current_catalog) > 0:
            return "Results outdated. Press Ctrl+R to rerun SEP."
        return ""

    def build_table_rows(self, catalog: SourceCatalog | None) -> list[TableRowViewModel]:
        """Transform a domain catalog into source-table row view models."""

        if catalog is None:
            return []
        visible_columns = self._visible_source_table_columns()
        return [
            TableRowViewModel(row_index=i, values=row)
            for i, row in enumerate(catalog.to_rows(visible_columns))
        ]

    def build_table_selection_state(self, selected_row: int | None = None) -> TableSelectionState:
        """Construct the source-table selection state."""

        row_count = 0 if self.current_catalog is None else len(self.current_catalog)
        return TableSelectionState(selected_row=selected_row, row_count=row_count)

    def build_table_view_state(self, selected_row: int | None = None) -> TableViewState:
        """Construct the composite source-table view state."""

        has_catalog = self.current_catalog is not None and len(self.current_catalog) > 0
        feedback = self.build_empty_catalog_feedback()
        if self._is_sep_extract_running():
            feedback = self.build_loading_catalog_feedback()
        if has_catalog:
            feedback = ViewFeedbackState(status="ready")
        return TableViewState(
            row_count=0 if self.current_catalog is None else len(self.current_catalog),
            has_catalog=has_catalog,
            selection=self.build_table_selection_state(selected_row=selected_row),
            feedback=feedback,
        )

    def build_canvas_image_state(self) -> CanvasImageState:
        """Construct the image-canvas presentation state."""

        current_data = self.fits_service.current_data
        if current_data is None or current_data.data is None:
            return CanvasImageState(feedback=self.build_empty_image_feedback())
        height, width = current_data.data.shape[:2]
        feedback = ViewFeedbackState(status="ready")
        if self._is_frame_rendering(self._current_frame_index) and not self._is_playback_active():
            feedback = self.build_rendering_image_feedback(
                has_preview=self._current_frame_has_preview_image()
            )
        return CanvasImageState(
            width=width,
            height=height,
            has_image=True,
            feedback=feedback,
        )

    def build_canvas_overlay_state(self, highlighted_index: int | None = None) -> CanvasOverlayState:
        """Construct the overlay presentation state for the canvas."""

        source_count = 0 if self.current_catalog is None else len(self.current_catalog)
        feedback = self.build_empty_catalog_feedback()
        if self._is_sep_extract_running():
            feedback = self.build_loading_catalog_feedback()
        if source_count:
            feedback = ViewFeedbackState(status="ready")
        return CanvasOverlayState(
            source_count=source_count,
            highlighted_index=highlighted_index,
            feedback=feedback,
        )

    def build_header_view_state(self) -> HeaderViewState:
        """Construct the composite header-dialog state."""

        current_data = self.fits_service.current_data
        if current_data is None:
            return HeaderViewState(
                has_header=False,
                line_count=0,
                feedback=self.build_no_header_feedback(),
            )
        return HeaderViewState(
            has_header=current_data.header is not None,
            line_count=0,
            feedback=ViewFeedbackState(status="ready"),
        )

    def build_sep_panel_state(self) -> SEPPanelState:
        """Construct the composite SEP-panel state."""

        enablement = self.build_sep_enablement_state()
        feedback = ViewFeedbackState(status="ready")
        if not enablement.enabled:
            feedback = self.build_disabled_sep_feedback(enablement.reason)
        return SEPPanelState(enablement=enablement, feedback=feedback)

    def build_sep_enablement_state(self) -> ControlEnablementState:
        """Construct the SEP panel enablement state."""

        has_image = self.fits_service.current_data is not None
        if self._is_sep_extract_running():
            return ControlEnablementState(
                enabled=False,
                reason="SEP extraction is running in the background.",
            )
        return ControlEnablementState(
            enabled=has_image,
            reason="" if has_image else "SEP extraction is unavailable until a FITS image is loaded.",
        )

    def build_empty_image_feedback(self) -> ViewFeedbackState:
        """Feedback shown when no FITS image is loaded."""

        return ViewFeedbackState(
            status="empty",
            title="No Image Loaded",
            detail=(
                "Drop FITS files here or press Ctrl+O.\n"
                "Wheel to zoom, drag to pan, and right-drag a ROI to run SEP."
            ),
            visible=True,
        )

    def build_rendering_image_feedback(self, *, has_preview: bool) -> ViewFeedbackState:
        """Feedback shown while the current frame is rendering in the background."""

        title = "Rendering Full Frame" if has_preview else "Rendering Preview"
        detail = (
            "Preview shown while the full-resolution render finishes."
            if has_preview
            else "Preparing the first visible render for this frame."
        )
        return ViewFeedbackState(
            status="loading",
            title=title,
            detail=detail,
            visible=True,
        )

    def build_empty_catalog_feedback(self) -> ViewFeedbackState:
        """Feedback shown when no source catalog is available."""

        return ViewFeedbackState(
            status="empty",
            title="No Sources",
            detail="Run SEP on a ROI to populate source overlays and the source table.",
            visible=True,
        )

    def build_loading_catalog_feedback(self) -> ViewFeedbackState:
        """Feedback shown while SEP extraction is still in flight."""

        return ViewFeedbackState(
            status="loading",
            title="Extracting Sources",
            detail="SEP is running in the background for the selected region.",
            visible=True,
        )

    def build_no_header_feedback(self) -> ViewFeedbackState:
        """Feedback shown when no header content is available."""

        return ViewFeedbackState(
            status="empty",
            title="No Header",
            detail="Open a FITS file before viewing header cards.",
            visible=True,
        )

    def build_disabled_sep_feedback(self, reason: str) -> ViewFeedbackState:
        """Feedback shown when the SEP panel is disabled."""

        return ViewFeedbackState(
            status="disabled",
            title="SEP Unavailable",
            detail=reason,
            visible=True,
        )

    def build_error_feedback(self, title: str, detail: str) -> ViewFeedbackState:
        """Build a generic error-state payload for any passive view."""

        return ViewFeedbackState(status="error", title=title, detail=detail, visible=True)

    def run_sep_extract(self) -> None:
        """User-triggered SEP extraction: show docks and run full-image extract."""

        data = self.fits_service.current_data
        if data is None or data.data is None:
            self.show_error("SEP", "No FITS image loaded.")
            return

        if self.source_table_dock is not None:
            self.source_table_dock.show()
            self.source_table_dock.show_cutout_tab()
            self.source_table_dock.raise_()
        if self.sep_panel_dock is not None:
            self.sep_panel_dock.show()

        h, w = data.data.shape[:2]
        self._start_sep_extract(ROISelection(x0=0, y0=0, width=w, height=h))

    def _show_marker_dock(self) -> None:
        """Show the marker dock panel."""

        if self.marker_dock is not None:
            self.marker_dock.show()
            self.marker_dock.raise_()

    def _show_target_info_fields_dialog(self) -> None:
        """Open the source-field selection dialog from the menu bar."""

        if self.source_table_dock is None:
            return

        dialog = CatalogFieldDialog(self.source_table_dock.columns, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.source_table_dock.configure_columns(dialog.selected_columns())
        self._persist_catalog_preferences()
        self.sync_catalog_views()

    def _visible_source_table_columns(self) -> list[str]:
        """Return enabled source-table column keys in display order."""

        if self.source_table_dock is None:
            return list(SourceCatalog.COLUMN_NAMES)
        mandatory_value = getattr(self.source_table_dock, "MANDATORY_COLUMN_KEYS", ("ID", "X", "Y"))
        if not isinstance(mandatory_value, (list, tuple)):
            mandatory_value = ("ID", "X", "Y")
        mandatory = set(mandatory_value)
        return [
            column.key
            for column in self.source_table_dock.columns
            if column.visible or column.key in mandatory
        ]

    def _refresh_histogram_view(self) -> None:
        """Push the current image histogram and manual limits into the histogram dock."""

        if self.histogram_dock is None:
            return
        if not self.histogram_dock.isVisible():
            return

        counts, min_value, max_value = self.fits_service.histogram()
        if counts.size == 0 or (counts.sum() == 0 and min_value == 0.0 and max_value == 0.0):
            self.histogram_dock.clear_histogram()
            return

        manual_limits = None
        if self.fits_service.current_interval == "Manual":
            manual_limits = self.fits_service.manual_interval_limits

        self.histogram_dock.set_histogram(
            counts,
            min_value,
            max_value,
            manual_limits=manual_limits,
        )

    def _handle_histogram_visibility_changed(self, visible: bool) -> None:
        """Compute the histogram lazily the first time the dock becomes visible."""

        if visible:
            self._refresh_histogram_view()

    def _handle_histogram_manual_range(self, low: float, high: float) -> None:
        """Switch the renderer into Manual mode using histogram-selected limits."""

        self.fits_service.set_manual_interval_limits(low, high)
        self.fits_service.set_interval("Manual")
        self._persist_render_preferences()
        self.sync_render_controls()
        if self.fits_service.current_data is not None:
            self._rerender_all_frames()
            self._show_current_frame_image()
        self._refresh_histogram_view()

    def _handle_histogram_auto_range(self) -> None:
        """Return from Manual interval mode to the most recent automatic interval."""

        self.fits_service.set_interval(self._last_auto_interval_name or "ZScale")
        self._persist_render_preferences()
        self.sync_render_controls()
        if self.fits_service.current_data is not None:
            self._rerender_all_frames()
            self._show_current_frame_image()
        self._refresh_histogram_view()

    def _is_sep_extract_running(self) -> bool:
        """Return whether a background SEP extraction is currently active."""

        return self._active_sep_request_id is not None

    def _cancel_active_sep_extract(self, *, wait: bool = False) -> None:
        """Request shutdown for any active SEP worker thread."""

        thread = self._sep_thread
        if thread is None or not thread.isRunning():
            self._active_sep_request_id = None
            return

        thread.requestInterruption()
        thread.quit()
        if wait:
            thread.wait()
            self._clear_sep_worker_refs()

    def _clear_sep_worker_refs(self) -> None:
        """Drop references to the current SEP worker/thread pair after shutdown."""

        self._sep_thread = None
        self._sep_worker = None
        self._active_sep_request_id = None

    def _start_sep_extract(self, roi: ROISelection) -> None:
        """Start asynchronous SEP extraction for the given image-space ROI."""

        if self._is_sep_extract_running():
            if self.app_status_bar is not None:
                self.app_status_bar.showMessage("SEP extraction is already running.", 3000)
            return

        data = self.fits_service.current_data
        if data is None or data.data is None:
            self.show_error("SEP", "No FITS image loaded.")
            return

        h, w = data.data.shape[:2]
        x0 = max(0, min(roi.x0, w))
        y0 = max(0, min(roi.y0, h))
        x1 = max(x0, min(roi.x0 + roi.width, w))
        y1 = max(y0, min(roi.y0 + roi.height, h))
        if x1 <= x0 or y1 <= y0:
            self.show_error("SEP", "Selected ROI is empty.")
            return

        normalized_roi = ROISelection(x0=x0, y0=y0, width=x1 - x0, height=y1 - y0)
        subarray = data.data[y0:y1, x0:x1]
        params = self.sep_panel.params_from_form_state() if self.sep_panel else self.sep_service.params

        self._sep_request_id += 1
        request_id = self._sep_request_id
        self._active_sep_request_id = request_id
        self.current_catalog = None
        self._catalog_results_stale = False
        self._clear_latest_error()

        self._sep_thread = QThread(self)
        self._sep_worker = SEPExtractWorker(
            request_id=request_id,
            data_subarray=subarray,
            roi=normalized_roi,
            params=params,
            wcs=data.wcs if data.has_wcs else None,
        )
        self._sep_worker.moveToThread(self._sep_thread)

        self._sep_thread.started.connect(self._sep_worker.run)
        self._sep_worker.extraction_ready.connect(self._handle_sep_extraction_ready)
        self._sep_worker.extraction_error.connect(self._handle_sep_extraction_error)
        self._sep_worker.finished.connect(self._handle_sep_extraction_finished)
        self._sep_worker.finished.connect(self._sep_thread.quit)
        self._sep_worker.finished.connect(self._sep_worker.deleteLater)
        self._sep_thread.finished.connect(self._sep_thread.deleteLater)
        self._sep_thread.finished.connect(self._clear_sep_worker_refs)

        if self.source_table_dock is not None:
            self.source_table_dock.show()
            self.source_table_dock.set_row_view_models([])
            self.source_table_dock.set_view_state(self.build_table_view_state())
            self.source_table_dock.show_cutout_tab()
            self.source_table_dock.raise_()
        if self.sep_panel_dock is not None:
            self.sep_panel_dock.show()
        if self.canvas is not None:
            self.canvas.clear_sources()
            self.canvas.set_overlay_state(self.build_canvas_overlay_state())
        self._set_status_activity(
            kind="sep",
            text=f"Running SEP extraction on {normalized_roi.width}x{normalized_roi.height} ROI...",
            progress_value=0,
            progress_max=0,
            cancellable=False,
        )
        self.sync_sep_panel_state()
        self.sync_render_controls()
        self._sep_thread.start()

    def _handle_sep_extraction_ready(self, request_id: int, roi: ROISelection, catalog: SourceCatalog) -> None:
        """Accept a SEP extraction result if it still matches the latest request."""

        if request_id != self._active_sep_request_id:
            return

        self._catalog_results_stale = False
        self.set_current_catalog(catalog)
        self.sync_catalog_views()
        if len(catalog) == 1:
            self.handle_source_clicked(0)
        if self.app_status_bar is not None:
            self.app_status_bar.showMessage(
                f"Extracted {len(catalog)} source{'s' if len(catalog) != 1 else ''} from ROI "
                f"{roi.width}x{roi.height}.",
                4000,
            )

    def _handle_sep_extraction_error(self, request_id: int, detail: str) -> None:
        """Report a SEP extraction failure if it still matches the latest request."""

        if request_id != self._active_sep_request_id:
            return

        self.show_error("SEP extraction failed", detail)
        if self.source_table_dock is not None:
            self.source_table_dock.set_view_state(self.build_table_view_state())

    def _handle_sep_extraction_finished(self, request_id: int) -> None:
        """Finalize SEP-extraction UI state when a worker exits."""

        if request_id == self._active_sep_request_id:
            self._clear_status_activity(kind="sep")
            self._active_sep_request_id = None
            self.sync_sep_panel_state()
            if self.source_table_dock is not None:
                self.source_table_dock.set_view_state(self.build_table_view_state())
            if self.canvas is not None:
                self.canvas.set_overlay_state(self.build_canvas_overlay_state())
            self.sync_render_controls()

    def _apply_markers(self, entries: list) -> None:
        """Draw markers on the canvas. Converts WCS entries to pixel coords."""

        if self.canvas is None or self.marker_dock is None:
            return

        pixel_coords: list[tuple[float, float]] = []
        data = self.fits_service.current_data
        wcs = data.wcs if data is not None and data.has_wcs else None

        for entry in entries:
            if len(entry) == 3:
                coord_type, v1, v2 = entry
            else:
                coord_type, v1, v2 = "pixel", entry[0], entry[1]

            if coord_type == "wcs":
                if wcs is None:
                    self.show_error("Markers", "No WCS available for coordinate conversion.")
                    return
                try:
                    from astropy.coordinates import SkyCoord
                    import astropy.units as u
                    sky = SkyCoord(ra=v1 * u.deg, dec=v2 * u.deg)
                    px, py = wcs.world_to_pixel(sky)
                    pixel_coords.append((float(px), float(py)))
                except Exception as e:
                    self.show_error("Markers", f"WCS conversion failed: {e}")
                    return
            else:
                pixel_coords.append((v1, v2))

        self.canvas.set_markers(
            pixel_coords,
            radius=self.marker_dock.radius(),
            color=self.marker_dock.color(),
            line_width=self.marker_dock.line_width(),
        )

    def _handle_marker_color_changed(self, color: Any) -> None:
        """Keep ROI selection color aligned and repaint existing markers."""

        self._sync_marker_visual_style()
        if self.marker_dock is not None:
            entries = self.marker_dock.parse_coordinates()
            if entries:
                self._apply_markers(entries)

    def _handle_marker_line_width_changed(self, line_width: int) -> None:
        """Keep ROI selection width aligned and repaint existing markers."""

        self._sync_marker_visual_style()
        if self.marker_dock is not None:
            entries = self.marker_dock.parse_coordinates()
            if entries:
                self._apply_markers(entries)

    def _sync_marker_visual_style(self) -> None:
        """Apply the current marker color/width to ROI and source overlays."""

        if self.canvas is None or self.marker_dock is None:
            return

        color = self.marker_dock.color()
        line_width = self.marker_dock.line_width()
        self.canvas.set_roi_color(color)
        self.canvas.set_roi_line_width(line_width)
        self.canvas.set_source_overlay_style(color=color, line_width=line_width)

    def reset_view_state(self) -> None:
        """Clear image, overlays, table state, dialog state, and status labels."""

        if self.canvas is not None:
            self.canvas.clear_image()
            self.canvas.clear_sources()
            self.canvas.clear_markers()
            self.canvas.set_image_state(self.build_canvas_image_state())
            self.canvas.set_overlay_state(self.build_canvas_overlay_state())
        if self.source_table_dock is not None:
            self.source_table_dock.clear_catalog()
            self.source_table_dock.set_view_state(self.build_table_view_state())
        if self.header_dialog is not None:
            self.header_dialog.clear()
            self.header_dialog.set_view_state(self.build_header_view_state())
        if self.app_status_bar is not None:
            self.app_status_bar.clear_data()
        if self.histogram_dock is not None:
            self.histogram_dock.clear_histogram()
        self.sync_sep_panel_state()
        self.sync_render_controls()

    def set_current_catalog(self, catalog: SourceCatalog | None) -> None:
        """Update the active catalog reference held by the window."""

        self.current_catalog = catalog

    def export_catalog(self) -> None:
        """Export the current source catalog to CSV.

        Main flow:
        `MainWindow.export_catalog()` -> `SourceCatalog.to_csv(path)`.
        """

        if self.current_catalog is None or len(self.current_catalog) == 0:
            self.show_error("Export", "No source catalog to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Catalog", "catalog.csv", "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            self.current_catalog.to_csv(path, columns=self._visible_source_table_columns())
            if self.app_status_bar is not None:
                self.app_status_bar.showMessage(f"Exported {len(self.current_catalog)} sources to {path}", 3000)
        except Exception as e:
            self.show_error("Export failed", str(e))

    def show_header_dialog(self) -> None:
        """Open the FITS header viewer.

        Main flow:
        `MainWindow.show_header_dialog()` -> `FITSService.header_text()`
        -> `HeaderDialog.set_header_text()`.
        """

        if self.header_dialog is None:
            return
        text = self.fits_service.header_text()
        self.header_dialog.set_header_text(text)
        self.header_dialog.show()
        self.header_dialog.raise_()

    def handle_roi_selected(self, x0: int, y0: int, width: int, height: int) -> None:
        """Handle ROI selection from the canvas and trigger SEP extraction.

        ROI arrives in displayed-image coords; remap to original frame so SEP
        always operates on the unrotated data.
        """

        shape = self._current_original_shape()
        if shape is not None and self._orientation != (False, False, False):
            w, h = shape
            x1d, y1d = x0 + width, y0 + height
            ox0, oy0 = self._unorient_point(x0, y0, w, h)
            ox1, oy1 = self._unorient_point(x1d, y1d, w, h)
            ox0, ox1 = sorted((int(round(ox0)), int(round(ox1))))
            oy0, oy1 = sorted((int(round(oy0)), int(round(oy1))))
            x0, y0, width, height = ox0, oy0, ox1 - ox0, oy1 - oy0
        self._start_sep_extract(ROISelection(x0=x0, y0=y0, width=width, height=height))

    def handle_roi_selection(self, selection: ROISelection) -> None:
        """Structured wrapper around the primitive ROI signal contract."""

        self.handle_roi_selected(selection.x0, selection.y0, selection.width, selection.height)

    def handle_source_clicked(self, index: int) -> None:
        """Handle source-table row selection and synchronize the canvas.

        Main flow:
        `SourceTableDock.source_clicked` -> `MainWindow.handle_source_clicked()`
        -> `ImageCanvas.highlight_source()`.
        """

        if self.canvas is not None:
            self.canvas.highlight_source(index)
            self.canvas.set_overlay_state(self.build_canvas_overlay_state(highlighted_index=index))
            self.canvas.center_on_source(index)
        if self.source_table_dock is not None and self.source_table_dock.current_selection_state().selected_row != index:
            self.source_table_dock.select_source(index)
        self._update_source_cutout(index)

    def _handle_source_hovered(self, index: int) -> None:
        """Highlight a source on the canvas as the user hovers its row."""

        if self.canvas is None:
            return
        self.canvas.highlight_source(index)
        self.canvas.set_overlay_state(self.build_canvas_overlay_state(highlighted_index=index))

    def handle_sep_params_changed(self, params: Any) -> None:
        """Receive updated SEP parameters from the parameter panel.

        Current contract:
        - update window-side extraction context only
        - do not trigger extraction automatically
        """

        if params is not None:
            old = self.sep_service.params
            self.sep_service.params = params
            if old != params and self.current_catalog is not None and len(self.current_catalog) > 0:
                self._catalog_results_stale = True
                if self.app_status_bar is not None:
                    self.app_status_bar.showMessage(
                        "SEP settings changed. Current source results are outdated until rerun.",
                        4000,
                    )
                if self.source_table_dock is not None:
                    self.source_table_dock.set_status_note(self._catalog_status_note())
                self.sync_sep_panel_state()
            if (
                old.bkg_box_size != params.bkg_box_size
                or old.bkg_filter_size != params.bkg_filter_size
            ):
                self._invalidate_bkg_caches()

    def update_status_from_cursor(self, x: float, y: float) -> None:
        """Update status-bar information from the current cursor position.

        Main flow:
        `ImageCanvas.mouse_moved` -> `MainWindow.update_status_from_cursor()`
        -> `FITSData.sample_pixel()` -> `AppStatusBar.set_sample()`.
        """

        data = self.fits_service.current_data
        if data is None or data.data is None:
            return
        h, w = data.data.shape[:2]
        ox, oy = self._unorient_point(x, y, w, h)
        sample = data.sample_pixel(int(ox), int(oy))
        self.apply_pixel_sample(sample)

    def apply_pixel_sample(self, sample: PixelSample) -> None:
        """Forward a prepared pixel sample into the status bar."""

        if self.app_status_bar is not None:
            self.app_status_bar.set_sample(sample)

    def handle_zoom_changed(self, zoom_factor: float) -> None:
        """Receive zoom updates from the canvas and refresh the status bar."""

        if self.app_status_bar is not None:
            self.app_status_bar.set_zoom_info(zoom_factor)

    def collect_ui_state(self) -> dict[str, Any]:
        """Return a snapshot of coarse window state for debugging and tests.

        Intended contents:
        - whether a file is loaded
        - whether a catalog is present
        - current stretch/interval selection
        - availability of major widgets and actions
        """

        return {
            "has_canvas": self.canvas is not None,
            "has_source_table": self.source_table_dock is not None,
            "has_sep_panel": self.sep_panel is not None,
            "has_status_bar": self.app_status_bar is not None,
            "has_file_loaded": self.fits_service.current_data is not None,
            "has_catalog": self.current_catalog is not None,
            "current_stretch": self.fits_service.current_stretch,
            "current_interval": self.fits_service.current_interval,
        }

    def show_error(self, title: str, detail: str) -> None:
        """Show an error message to the user."""

        logger.error("%s: %s", title, detail)
        self._latest_error_title = title
        self._latest_error_detail = detail
        if self.app_status_bar is not None:
            self.app_status_bar.show_error_indicator(title, detail)
            self.app_status_bar.showMessage(f"{title}: {detail}", 5000)

    def _handle_stretch_changed(self, name: str) -> None:
        """Update the selected stretch mode from the toolbar and re-render."""

        if name:
            self.fits_service.set_stretch(name)
            self._persist_render_preferences()
            if self.fits_service.current_data is not None:
                self._rerender_all_frames()
                self._show_current_frame_image()
                self._refresh_histogram_view()

    def _handle_interval_changed(self, name: str) -> None:
        """Update the selected interval mode from the toolbar and re-render."""

        if name:
            if name == "Manual":
                if self.fits_service.manual_interval_limits is None:
                    data_range = self.fits_service.finite_data_range()
                    if data_range is not None:
                        self.fits_service.set_manual_interval_limits(*data_range)
                self.fits_service.set_interval("Manual")
            else:
                self.fits_service.set_interval(name)
                self._last_auto_interval_name = name
            self._persist_render_preferences()
            if self.fits_service.current_data is not None:
                self._rerender_all_frames()
                self._show_current_frame_image()
                self._refresh_histogram_view()

    def _handle_preview_profile_changed(self, name: str) -> None:
        """Update preview aggressiveness for future loads and current rerenders."""

        profile_name = self._normalize_preview_profile_name(name)
        if profile_name == self._preview_profile_name:
            return

        self._preview_profile_name = profile_name
        self._persist_render_preferences()
        if self.fits_service.current_data is not None:
            self._rerender_all_frames()
            self._show_current_frame_image()
            self._refresh_histogram_view()

    # --- Frame management ---

    def _qimage_from_u8(self, image_u8: Any) -> QImage | None:
        """Convert an 8-bit grayscale numpy image into a detached QImage."""

        if image_u8 is None:
            return None
        image_u8 = np.ascontiguousarray(image_u8)
        h, w = image_u8.shape[:2]
        bytes_per_line = int(image_u8.strides[0])
        qimage = QImage(image_u8.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
        return qimage.copy()

    def _render_frame(self, data: Any) -> QImage | None:
        """Render a FITSData to QImage using the current stretch/interval."""

        self.fits_service.current_data = data
        result = self.fits_service.render()
        return self._qimage_from_u8(result.image_u8)

    def _update_source_cutout(self, index: int | None = None) -> None:
        """Refresh the selected-source cutout preview in the source-table dock."""

        if self.source_table_dock is None:
            return
        if index is None:
            index = self.source_table_dock.current_selection_state().selected_row
        if index is None or self.current_catalog is None:
            self.source_table_dock.clear_cutout_image()
            return

        record = self.current_catalog.get(index)
        data = self.fits_service.current_data
        if record is None or data is None or data.data is None:
            self.source_table_dock.clear_cutout_image()
            return

        x0, y0, x1, y1 = self._source_cutout_bounds(record, data.data.shape[:2])
        if x1 <= x0 or y1 <= y0:
            self.source_table_dock.clear_cutout_image()
            return

        image_u8 = self._build_source_cutout_review_image(record, x0, y0, x1, y1)
        if image_u8 is None:
            return
        self.source_table_dock.set_cutout_image(self._qimage_from_u8(image_u8))

    def _source_cutout_bounds(
        self,
        record: Any,
        shape: tuple[int, int],
        *,
        padding: int = 4,
        fallback_radius: int = 16,
    ) -> tuple[int, int, int, int]:
        """Return absolute frame-space bounds for the selected source review cutout."""

        height, width = shape
        bbox = getattr(record, "extra", {}) or {}
        if all(key in bbox for key in ("xmin", "xmax", "ymin", "ymax")):
            x0 = max(0, int(bbox["xmin"]) - padding)
            y0 = max(0, int(bbox["ymin"]) - padding)
            x1 = min(width, int(bbox["xmax"]) + padding + 1)
            y1 = min(height, int(bbox["ymax"]) + padding + 1)
            return x0, y0, x1, y1

        center_x = int(round(record.x))
        center_y = int(round(record.y))
        x0 = max(0, center_x - fallback_radius)
        y0 = max(0, center_y - fallback_radius)
        x1 = min(width, center_x + fallback_radius + 1)
        y1 = min(height, center_y + fallback_radius + 1)
        return x0, y0, x1, y1

    def _build_source_cutout_review_image(
        self,
        record: Any,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
    ) -> Any:
        """Build the current cutout review image for the selected source."""

        mode = ""
        if self.source_table_dock is not None:
            selected_mode = self.source_table_dock.current_cutout_mode()
            if isinstance(selected_mode, str):
                mode = selected_mode

        if mode in (SourceTableDock.CUTOUT_MODE_BACKGROUND, SourceTableDock.CUTOUT_MODE_RESIDUAL):
            return self._build_bkg_or_residual_cutout(mode, x0, y0, x1, y1)

        if mode == SourceTableDock.CUTOUT_MODE_CONNECTED_REGION:
            connected_region = self._build_connected_region_cutout(record, x0, y0, x1, y1)
            if connected_region is not None:
                return connected_region
            if self.source_table_dock is not None:
                self.source_table_dock.clear_cutout_image("Connected region unavailable.")
            return None

        from ..core.fits_data import FITSData
        from ..core.fits_service import render_image_u8

        data = self.fits_service.current_data
        cutout = data.data[y0:y1, x0:x1]
        return render_image_u8(
            FITSData(data=cutout),
            self.fits_service.current_stretch,
            self.fits_service.current_interval,
            manual_limits=self.fits_service.manual_interval_limits,
        )

    def _build_bkg_or_residual_cutout(
        self,
        mode: str,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
    ) -> Any:
        """Render a cutout from the cached background or residual image."""

        idx = self._current_frame_index
        if not (0 <= idx < len(self._frames)):
            return None
        substitute = (
            self._frame_bkg_cache[idx]
            if mode == SourceTableDock.CUTOUT_MODE_BACKGROUND
            else self._frame_residual_cache[idx]
        )
        if substitute is None or substitute.data is None:
            self._dispatch_bkg_worker(idx)
            if self.source_table_dock is not None:
                self.source_table_dock.clear_cutout_image("正在计算背景...")
            return None

        from ..core.fits_data import FITSData
        from ..core.fits_service import render_image_u8

        cutout = substitute.data[y0:y1, x0:x1]
        return render_image_u8(
            FITSData(data=cutout),
            self.fits_service.current_stretch,
            self.fits_service.current_interval,
            manual_limits=None,
        )

    def _build_connected_region_cutout(
        self,
        record: Any,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
    ) -> np.ndarray | None:
        """Return a grayscale view of the selected source's connected region."""

        if self.current_catalog is None or self.current_catalog.segmentation_map is None:
            return None

        segmap = self.current_catalog.segmentation_map
        seg_height, seg_width = segmap.shape[:2]
        local_x0 = max(0, x0 - self.current_catalog.roi_x0)
        local_y0 = max(0, y0 - self.current_catalog.roi_y0)
        local_x1 = min(seg_width, x1 - self.current_catalog.roi_x0)
        local_y1 = min(seg_height, y1 - self.current_catalog.roi_y0)
        if local_x1 <= local_x0 or local_y1 <= local_y0:
            return None

        seg_cutout = segmap[local_y0:local_y1, local_x0:local_x1]
        selected_mask = seg_cutout == int(record.source_id)
        if not np.any(selected_mask):
            return None

        image = np.zeros(seg_cutout.shape, dtype=np.uint8)
        image[(seg_cutout > 0) & ~selected_mask] = 96
        image[selected_mask] = 255
        return image

    def _rerender_all_frames(self) -> None:
        """Mark all frames dirty and re-render only the current frame."""

        self._render_generation += 1
        self._playback_render_queue.clear()
        self._playback_bg_render_ids.clear()
        self._cancel_active_frame_renders(wait=False)
        self._render_request_index_by_id.clear()
        self._latest_render_request_by_index.clear()
        for i in range(len(self._frames)):
            self._frame_dirty[i] = True
        self._sync_current_canvas_image_state()
        self._ensure_frame_rendered(self._current_frame_index)
        if self._is_playback_active():
            self._build_playback_render_queue()
            self._pump_playback_render_queue()

    def _ensure_frame_rendered(self, index: int) -> None:
        """Schedule background rendering for a dirty frame."""

        if index < 0 or index >= len(self._frames):
            return
        if not self._frame_dirty[index]:
            return
        self._schedule_frame_render(index)

    def _activate_frame(self, index: int) -> None:
        """Switch to frame at index: update service, canvas, title, controls."""

        if index < 0 or index >= len(self._frames):
            return

        self._cancel_active_sep_extract(wait=True)
        self._current_frame_index = index
        data = self._frames[index]
        self.fits_service.current_data = data
        self.current_catalog = None

        label = data.path or f"Frame {index}"
        if len(self._frames) > 1:
            self._set_window_title(f"{label} [{index + 1}/{len(self._frames)}]")
        else:
            self._set_window_title(label)

        if self.canvas is not None:
            x_axis, y_axis = self._axis_directions()
            self.canvas.compass.set_axes(x_axis, y_axis)
            shape = self._current_original_shape()
            if shape is not None and self._orientation != (False, False, False):
                w, h = shape
                self.canvas.set_source_position_transform(
                    lambda px, py, w=w, h=h: self._orient_point(px, py, w, h)
                )
            else:
                self.canvas.set_source_position_transform(None)
        self._show_current_frame_image()
        self.sync_render_controls()

        if self.canvas is not None:
            self.canvas.set_image_state(self.build_canvas_image_state())
            self.canvas.set_overlay_state(self.build_canvas_overlay_state())
            if len(self._frames) == 1:
                self.canvas.show_actual_pixels()
                self.canvas.centerOn(self.canvas._pixmap_item)

        if self.app_status_bar is not None:
            self.app_status_bar.set_frame_info(index, len(self._frames))

        self.sync_sep_panel_state()
        if self.source_table_dock is not None:
            self.source_table_dock.set_row_view_models([])
            self.source_table_dock.set_view_state(self.build_table_view_state())
        self._refresh_histogram_view()
        self._ensure_frame_rendered(index)
        self._prewarm_adjacent_frame()
        self._persist_session_state()

    def _show_current_frame_image(self) -> None:
        """Push the cached QImage for the current frame into the canvas."""

        if self.canvas is None:
            return
        view_state = self.canvas.capture_view_state()
        idx = self._current_frame_index
        if 0 <= idx < len(self._frame_images):
            img = self._frame_images[idx]
            if img is None:
                self.canvas.clear_image()
                return
            self.canvas.set_image(self._orient_qimage(img))
            self.canvas.restore_view_state(view_state)
        else:
            self.canvas.clear_image()

    def _sync_current_canvas_image_state(self) -> None:
        """Refresh the current canvas feedback from render/load state."""

        if self.canvas is not None:
            self.canvas.set_image_state(self.build_canvas_image_state())
        self._sync_frame_player_render_state()

    def _is_frame_rendering(self, index: int) -> bool:
        """Return whether the given frame still has a background render pending."""

        return 0 <= index < len(self._frame_dirty) and self._frame_dirty[index]

    def _current_frame_has_preview_image(self) -> bool:
        """Return whether the active frame already has a visible preview image."""

        idx = self._current_frame_index
        return 0 <= idx < len(self._frame_images) and self._frame_images[idx] is not None

    def _sync_frame_player(self) -> None:
        """Update frame player dock state and visibility."""

        if self.frame_player_dock is None:
            return
        count = len(self._frames)
        self.frame_player_dock.set_frame_count(count)
        self.frame_player_dock.set_current_frame(self._current_frame_index)
        if count > 1:
            self.frame_player_dock.show()
        else:
            self.frame_player_dock.hide()
        self._sync_frame_player_render_state()

    def _sync_frame_player_render_state(self) -> None:
        """Push current-frame render progress into the frame-player dock."""

        if self.frame_player_dock is None:
            return

        index = self._current_frame_index
        has_frames = 0 <= index < len(self._frames)
        is_rendering = has_frames and self._is_frame_rendering(index) and not self._is_playback_active()
        has_preview = has_frames and self._current_frame_has_preview_image()
        self.frame_player_dock.set_render_state(is_rendering, has_preview=has_preview)

    def _switch_frame(self, index: int) -> None:
        """Handle frame change signal from the player dock."""

        self._update_frame_step_direction(self._current_frame_index, index)
        self._activate_frame(index)
        if self.frame_player_dock is not None:
            self.frame_player_dock.set_current_frame(index)

    def _update_frame_step_direction(self, previous_index: int, next_index: int) -> None:
        """Track the most recent frame-navigation direction for prewarming."""

        if next_index == previous_index:
            return

        last_index = len(self._frames) - 1
        if previous_index == last_index and next_index == 0:
            self._frame_step_direction = 1
        elif previous_index == 0 and next_index == last_index:
            self._frame_step_direction = -1
        else:
            self._frame_step_direction = 1 if next_index > previous_index else -1

    def _preferred_adjacent_frame_index(self) -> int | None:
        """Return the most likely next frame to view, if any."""

        count = len(self._frames)
        if count < 2:
            return None

        candidate = self._current_frame_index + self._frame_step_direction
        last_index = count - 1

        if 0 <= candidate <= last_index:
            return candidate

        if self.frame_player_dock is None:
            return None

        if self.frame_player_dock.bounce_btn.isChecked():
            bounce_candidate = self._current_frame_index - self._frame_step_direction
            if 0 <= bounce_candidate <= last_index:
                return bounce_candidate
            return None

        if self.frame_player_dock.loop_btn.isChecked():
            return candidate % count

        return None

    def _prewarm_adjacent_frame(self) -> None:
        """Opportunistically pre-render the likely next frame for smoother stepping."""

        candidate = self._preferred_adjacent_frame_index()
        if candidate is None:
            return
        if self._view_mode != "original" and not self._frame_bkg_cached(candidate):
            self._dispatch_bkg_worker(candidate)
            return
        if not self._frame_dirty[candidate]:
            return
        self._schedule_frame_render(candidate)

    def _append_frames(self) -> None:
        """Append additional FITS files to the frame list."""

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Append FITS Frame(s)",
            self._last_open_directory(),
            "FITS Files (*.fits *.fit *.fts);;All Files (*)",
        )
        if not paths:
            return

        self._open_paths(paths, append=True)

    def _last_open_directory(self) -> str:
        """Return the most recently used FITS directory for file dialogs."""

        value = self._settings.value("paths/last_open_dir", "", type=str)
        return value or ""

    def _remember_open_directory(self, paths: list[str]) -> None:
        """Persist the parent directory of the most recently opened FITS path."""

        if not paths:
            return

        directory = str(Path(paths[0]).parent)
        if directory:
            self._settings.setValue("paths/last_open_dir", directory)

    def closeEvent(self, event: Any) -> None:
        """Stop any active background load before the window closes."""

        self._stop_active_frame_load(wait=True)
        self._cancel_active_frame_renders(wait=True)
        self._cancel_bkg_workers(wait=True)
        self._cancel_active_sep_extract(wait=True)
        self._persist_window_state()
        super().closeEvent(event)

    def _go_prev_frame(self) -> None:
        if len(self._frames) > 1 and self._current_frame_index > 0:
            self._switch_frame(self._current_frame_index - 1)

    def _go_next_frame(self) -> None:
        if len(self._frames) > 1 and self._current_frame_index < len(self._frames) - 1:
            self._switch_frame(self._current_frame_index + 1)
