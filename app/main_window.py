from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, Qt, QThread, QSettings, QTimer
from PySide6.QtGui import QAction, QImage, QKeySequence
from PySide6.QtWidgets import QComboBox, QDockWidget, QFileDialog, QLabel, QMainWindow, QToolBar

from ..core import FITSService, OpenFileRequest, PixelSample, ROISelection, SEPService, SourceCatalog
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
from .frame_render_worker import FrameRenderWorker
from .header_dialog import HeaderDialog
from .marker_dock import MarkerDock
from .sep_panel import SEPParamsPanel
from .source_table import SourceTableDock
from .status_bar import AppStatusBar


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
        self.header_dialog: HeaderDialog | None = None
        self.app_status_bar: AppStatusBar | None = None

        self.menu_file: Any = None
        self.menu_view: Any = None
        self.menu_tools: Any = None
        self.menu_help: Any = None

        self.main_toolbar: Any = None
        self.stretch_selector: Any = None
        self.interval_selector: Any = None
        self.preview_profile_selector: Any = None

        self.action_open_file: QAction | None = None
        self.action_export_catalog: QAction | None = None
        self.action_show_header: QAction | None = None
        self.action_close_file: QAction | None = None
        self.action_quit: QAction | None = None
        self.action_fit_to_window: QAction | None = None
        self.action_actual_pixels: QAction | None = None
        self.action_zoom_in: QAction | None = None
        self.action_zoom_out: QAction | None = None
        self.action_run_sep: QAction | None = None
        self.action_show_markers: QAction | None = None
        self.action_append_frames: QAction | None = None
        self.action_target_info_fields: QAction | None = None

        self.fits_service = fits_service or FITSService()
        self.sep_service = sep_service or SEPService()
        self.current_catalog: SourceCatalog | None = None
        self._settings = QSettings("AstroView", "AstroView")
        self._preview_profile_name = self.DEFAULT_PREVIEW_PROFILE

        from ..core.fits_data import FITSData
        self._frames: list[FITSData] = []
        self._frame_images: list[QImage | None] = []
        self._frame_dirty: list[bool] = []
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
        self._startup_request_applied = False

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

    def configure_window_shell(self) -> None:
        """Set window title, default size, dock policy, and startup flags."""

        self.setObjectName("main_window")
        self.setWindowTitle("AstroView")
        self.resize(1440, 900)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks
        )

    def build_central_canvas(self) -> None:
        """Create the central `ImageCanvas` and register it as the main view."""

        self.canvas = ImageCanvas(self)
        self.setCentralWidget(self.canvas)

    def build_docks(self) -> None:
        """Create dock widgets for the source table and SEP parameters panel."""

        self.source_table_dock = SourceTableDock(self)
        self.source_table_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.sep_panel = SEPParamsPanel(self)
        self.sep_panel_dock = QDockWidget("SEP Params", self)
        self.sep_panel_dock.setObjectName("sep_panel_dock")
        self.sep_panel_dock.setWidget(self.sep_panel)
        self.sep_panel_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.source_table_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.sep_panel_dock)
        self.splitDockWidget(
            self.source_table_dock,
            self.sep_panel_dock,
            Qt.Orientation.Vertical,
        )
        self.source_table_dock.hide()
        self.sep_panel_dock.hide()

        self.marker_dock = MarkerDock(self)
        self.marker_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.marker_dock)
        self.marker_dock.hide()

        self.frame_player_dock = FramePlayerDock(self)
        self.frame_player_dock.setAllowedAreas(
            Qt.DockWidgetArea.TopDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.frame_player_dock)
        self.frame_player_dock.hide()

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
        if self.action_fit_to_window is not None:
            self.menu_view.addAction(self.action_fit_to_window)
        if self.action_actual_pixels is not None:
            self.menu_view.addAction(self.action_actual_pixels)
        if self.action_zoom_in is not None:
            self.menu_view.addAction(self.action_zoom_in)
        if self.action_zoom_out is not None:
            self.menu_view.addAction(self.action_zoom_out)

        if self.action_run_sep is not None:
            self.menu_tools.addAction(self.action_run_sep)
        if self.action_show_markers is not None:
            self.menu_tools.addAction(self.action_show_markers)
        if self.action_target_info_fields is not None:
            self.menu_tools.addAction(self.action_target_info_fields)

        self.menu_view.addSeparator()
        if self.source_table_dock is not None:
            self.menu_view.addAction(self.source_table_dock.toggleViewAction())
        if self.sep_panel_dock is not None:
            self.menu_view.addAction(self.sep_panel_dock.toggleViewAction())
        if self.marker_dock is not None:
            self.menu_view.addAction(self.marker_dock.toggleViewAction())
        if self.frame_player_dock is not None:
            self.menu_view.addAction(self.frame_player_dock.toggleViewAction())

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
        self.action_export_catalog.setShortcut("Ctrl+E")
        self.action_show_header = QAction("Show Header", self)
        self.action_show_header.setShortcut("Ctrl+H")
        self.action_append_frames = QAction("Append Frames...", self)
        self.action_append_frames.setShortcut("Ctrl+Shift+O")
        self.action_close_file = QAction("Close File", self)
        self.action_close_file.setShortcut("Ctrl+W")
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

    def bind_canvas_signals(self) -> None:
        """Bind `ImageCanvas` signals to window controller methods."""

        if self.canvas is None:
            return
        self.canvas.mouse_moved.connect(self.update_status_from_cursor)
        self.canvas.roi_selected.connect(self.handle_roi_selected)
        self.canvas.zoom_changed.connect(self.handle_zoom_changed)

    def bind_source_table_signals(self) -> None:
        """Bind source-table signals to window controller methods."""

        if self.source_table_dock is None:
            return
        self.source_table_dock.source_clicked.connect(self.handle_source_clicked)

    def bind_sep_panel_signals(self) -> None:
        """Bind SEP-parameter panel signals to window controller methods."""

        if self.sep_panel is None:
            return
        self.sep_panel.params_changed.connect(self.handle_sep_params_changed)

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
        if self.marker_dock is not None:
            self.marker_dock.markers_updated.connect(self._apply_markers)
            self.marker_dock.color_changed.connect(self._handle_marker_color_changed)
            self.marker_dock.line_width_changed.connect(self._handle_marker_line_width_changed)
            self._sync_marker_visual_style()
        if self.frame_player_dock is not None:
            self.frame_player_dock.frame_changed.connect(self._switch_frame)

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

        self._remember_open_directory(paths)
        self._start_frame_load(paths, hdu_index=hdu_index, append=False)

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

        preview_profile = self._settings.value(
            "render/preview_profile",
            self._preview_profile_name,
            type=str,
        )
        self._preview_profile_name = self._normalize_preview_profile_name(preview_profile)

    def _restore_workspace_state(self) -> None:
        """Restore persisted marker preferences and window layout."""

        if self.marker_dock is not None:
            self.marker_dock.set_radius(self._settings.value("markers/radius", self.marker_dock.radius(), type=float))
            self.marker_dock.set_line_width(
                self._settings.value("markers/line_width", self.marker_dock.line_width(), type=int)
            )
            self.marker_dock.set_color(
                self._settings.value("markers/color", self.marker_dock.color().name(), type=str)
            )

        geometry = self._settings.value("window/geometry", QByteArray(), type=QByteArray)
        if geometry:
            self.restoreGeometry(geometry)

        state = self._settings.value("window/state", QByteArray(), type=QByteArray)
        if state:
            self.restoreState(state)

        self.sync_render_controls()
        self._sync_marker_visual_style()

    def _persist_render_preferences(self) -> None:
        """Store the current render-control selections."""

        self._settings.setValue("render/stretch", self.fits_service.current_stretch)
        self._settings.setValue("render/interval", self.fits_service.current_interval)
        self._settings.setValue("render/preview_profile", self._preview_profile_name)

    def _normalize_preview_profile_name(self, name: str | None) -> str:
        """Return a valid preview-profile name, falling back to the default."""

        if name in self.PREVIEW_PROFILE_CONFIGS:
            return str(name)
        return self.DEFAULT_PREVIEW_PROFILE

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

        self._render_threads.pop(request_id, None)
        self._render_workers.pop(request_id, None)
        self._render_request_index_by_id.pop(request_id, None)

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
        """Stop active render requests for frames other than the preferred one."""

        for request_id, index in list(self._render_request_index_by_id.items()):
            if index != preferred_index:
                self._cancel_frame_render_request(request_id, wait=wait)

    def _has_active_render_for_index(self, index: int) -> bool:
        """Return whether the given frame currently has a running render request."""

        request_id = self._latest_render_request_by_index.get(index)
        if request_id is None:
            return False
        thread = self._render_threads.get(request_id)
        return thread is not None and thread.isRunning()

    def _schedule_frame_render(self, index: int) -> None:
        """Render the requested frame in the background."""

        if index < 0 or index >= len(self._frames):
            return
        if not self._frame_dirty[index]:
            return
        if index != self._current_frame_index and self._has_active_render_for_index(self._current_frame_index):
            return

        request_id = self._latest_render_request_by_index.get(index)
        if request_id is not None:
            thread = self._render_threads.get(request_id)
            if thread is not None and thread.isRunning():
                return

        if index == self._current_frame_index:
            self._cancel_stale_frame_renders(index)

        self._render_request_id += 1
        request_id = self._render_request_id
        self._latest_render_request_by_index[index] = request_id
        self._render_request_index_by_id[request_id] = index

        thread = QThread(self)
        worker = FrameRenderWorker(
            request_id=request_id,
            generation=self._render_generation,
            frame_index=index,
            data=self._frames[index],
            stretch_name=self.fits_service.current_stretch,
            interval_name=self.fits_service.current_interval,
            preview_dimensions=self._preview_render_dimensions(),
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
        """Update action enablement and status-bar text for file loading."""

        for action in (self.action_open_file, self.action_append_frames, self.action_close_file):
            if action is not None:
                action.setEnabled(not is_loading)

        if self.app_status_bar is None:
            return

        if not is_loading:
            self.app_status_bar.clearMessage()
            return

        if total <= 0:
            self.app_status_bar.showMessage("Loading FITS files...")
            return

        filename = ""
        if current_path:
            filename = Path(current_path).name
        if filename:
            self.app_status_bar.showMessage(f"Loading FITS {loaded}/{total}: {filename}")
        else:
            self.app_status_bar.showMessage(f"Loading FITS {loaded}/{total}...")

    def _handle_loaded_frame(self, data: Any, preview_image_u8: Any = None) -> None:
        """Accept one loaded FITS frame from the background worker."""

        self._frames.append(data)
        if preview_image_u8 is not None:
            self._frame_images.append(self._qimage_from_u8(preview_image_u8))
        else:
            self._frame_images.append(None)
        self._frame_dirty.append(True)

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

    def close_current_file(self) -> None:
        """Close the current FITS file and reset the window state.

        Main flow:
        `MainWindow.close_current_file()` -> `FITSService.close_file()`
        -> clear canvas, table, dialog state, and status bar.
        """

        self._stop_active_frame_load(wait=True)
        self._cancel_active_frame_renders(wait=True)
        self._render_generation += 1
        self._render_request_index_by_id.clear()
        self._latest_render_request_by_index.clear()
        self._render_workers.clear()
        self.fits_service.close_file()
        self.current_catalog = None
        self._frames.clear()
        self._frame_images.clear()
        self._frame_dirty.clear()
        self._current_frame_index = 0
        self.setWindowTitle("AstroView")

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
        if self.app_status_bar is not None:
            self.app_status_bar.clear_data()
        if self.frame_player_dock is not None:
            self.frame_player_dock.set_frame_count(0)
            self.frame_player_dock.hide()
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
        if self.app_status_bar is not None:
            self.app_status_bar.clear_data()
        self.sync_render_controls()

    def sync_sep_panel_state(self) -> None:
        """Push current enablement/feedback state into the SEP parameter panel."""

        if self.sep_panel is not None:
            self.sep_panel.set_panel_state(self.build_sep_panel_state())

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
            self.source_table_dock.set_row_view_models(rows)
            self.source_table_dock.set_view_state(self.build_table_view_state())
        if self.canvas is not None:
            self.canvas.draw_sources(self.current_catalog)
            self.canvas.set_overlay_state(self.build_canvas_overlay_state())

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
        if self._is_frame_rendering(self._current_frame_index):
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
        return ControlEnablementState(
            enabled=has_image,
            reason="" if has_image else "SEP extraction is unavailable until a FITS image is loaded.",
        )

    def build_empty_image_feedback(self) -> ViewFeedbackState:
        """Feedback shown when no FITS image is loaded."""

        return ViewFeedbackState(
            status="empty",
            title="No Image Loaded",
            detail="Open a FITS file to populate the canvas.",
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
        if self.sep_panel_dock is not None:
            self.sep_panel_dock.show()

        h, w = data.data.shape[:2]
        self.handle_roi_selected(0, 0, w, h)

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
        self.sync_catalog_views()

    def _visible_source_table_columns(self) -> list[str]:
        """Return enabled source-table column keys in display order."""

        if self.source_table_dock is None:
            return list(SourceCatalog.COLUMN_NAMES)
        return [column.key for column in self.source_table_dock.columns if column.visible]

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

        pass

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

        Main flow:
        `ImageCanvas.roi_selected` -> `MainWindow.handle_roi_selected()`
        -> ROI slice from `FITSData`
        -> `SEPService.extract_from_roi()`
        -> `ImageCanvas.draw_sources()` + `SourceTableDock.populate()`.
        """

        data = self.fits_service.current_data
        if data is None or data.data is None:
            return

        h, w = data.data.shape[:2]
        x1 = min(x0 + width, w)
        y1 = min(y0 + height, h)
        x0 = max(x0, 0)
        y0 = max(y0, 0)
        subarray = data.data[y0:y1, x0:x1]

        roi = ROISelection(x0=x0, y0=y0, width=x1 - x0, height=y1 - y0)
        params = self.sep_panel.params_from_form_state() if self.sep_panel else None

        try:
            catalog = self.sep_service.extract_from_roi(
                subarray, roi, params=params, wcs=data.wcs if data.has_wcs else None,
            )
        except Exception as e:
            self.show_error("SEP extraction failed", str(e))
            return

        self.set_current_catalog(catalog)
        self.sync_catalog_views()

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

    def handle_sep_params_changed(self, params: Any) -> None:
        """Receive updated SEP parameters from the parameter panel.

        Current contract:
        - update window-side extraction context only
        - do not trigger extraction automatically
        """

        if params is not None:
            self.sep_service.params = params

    def update_status_from_cursor(self, x: float, y: float) -> None:
        """Update status-bar information from the current cursor position.

        Main flow:
        `ImageCanvas.mouse_moved` -> `MainWindow.update_status_from_cursor()`
        -> `FITSData.sample_pixel()` -> `AppStatusBar.set_sample()`.
        """

        data = self.fits_service.current_data
        if data is None:
            return
        sample = data.sample_pixel(int(x), int(y))
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

        if self.app_status_bar is not None:
            self.app_status_bar.showMessage(f"{title}: {detail}", 5000)

    def _handle_stretch_changed(self, name: str) -> None:
        """Update the selected stretch mode from the toolbar and re-render."""

        if name:
            self.fits_service.set_stretch(name)
            self._persist_render_preferences()
            if self.fits_service.current_data is not None:
                self._rerender_all_frames()
                self._show_current_frame_image()

    def _handle_interval_changed(self, name: str) -> None:
        """Update the selected interval mode from the toolbar and re-render."""

        if name:
            self.fits_service.set_interval(name)
            self._persist_render_preferences()
            if self.fits_service.current_data is not None:
                self._rerender_all_frames()
                self._show_current_frame_image()

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

    # --- Frame management ---

    def _qimage_from_u8(self, image_u8: Any) -> QImage | None:
        """Convert an 8-bit grayscale numpy image into a detached QImage."""

        if image_u8 is None:
            return None
        h, w = image_u8.shape[:2]
        qimage = QImage(image_u8.data, w, h, w, QImage.Format.Format_Grayscale8)
        return qimage.copy()

    def _render_frame(self, data: Any) -> QImage | None:
        """Render a FITSData to QImage using the current stretch/interval."""

        self.fits_service.current_data = data
        result = self.fits_service.render()
        return self._qimage_from_u8(result.image_u8)

    def _rerender_all_frames(self) -> None:
        """Mark all frames dirty and re-render only the current frame."""

        self._render_generation += 1
        self._cancel_active_frame_renders(wait=False)
        self._render_request_index_by_id.clear()
        self._latest_render_request_by_index.clear()
        for i in range(len(self._frames)):
            self._frame_dirty[i] = True
        self._sync_current_canvas_image_state()
        self._ensure_frame_rendered(self._current_frame_index)

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

        self._current_frame_index = index
        data = self._frames[index]
        self.fits_service.current_data = data
        self.current_catalog = None

        label = data.path or f"Frame {index}"
        if len(self._frames) > 1:
            self.setWindowTitle(f"AstroView — {label} [{index + 1}/{len(self._frames)}]")
        else:
            self.setWindowTitle(f"AstroView — {label}")

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
        self._ensure_frame_rendered(index)
        self._prewarm_adjacent_frame()

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
            self.canvas.set_image(img)
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
        is_rendering = has_frames and self._is_frame_rendering(index)
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

        self._remember_open_directory(paths)
        self._start_frame_load(paths, append=True)

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
        self._persist_window_state()
        super().closeEvent(event)

    def _go_prev_frame(self) -> None:
        if len(self._frames) > 1 and self._current_frame_index > 0:
            self._switch_frame(self._current_frame_index - 1)

    def _go_next_frame(self) -> None:
        if len(self._frames) > 1 and self._current_frame_index < len(self._frames) - 1:
            self._switch_frame(self._current_frame_index + 1)
