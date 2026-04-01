from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
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
from .canvas import ImageCanvas
from .frame_player_dock import FramePlayerDock
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

        self.fits_service = fits_service or FITSService()
        self.sep_service = sep_service or SEPService()
        self.current_catalog: SourceCatalog | None = None

        from ..core.fits_data import FITSData
        self._frames: list[FITSData] = []
        self._frame_images: list[QImage | None] = []
        self._current_frame_index: int = 0

    def initialize(self) -> None:
        """High-level bootstrap entry for the window skeleton.

        Intended sequence:
        1. `create_actions()`
        2. `build_ui()`
        3. `connect_signals()`
        4. `reset_view_state()`
        5. `apply_startup_request()`
        """

        self.create_actions()
        self.build_ui()
        self.connect_signals()
        self.reset_view_state()
        self.apply_startup_request()

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

        self.stretch_selector = QComboBox(self)
        self.stretch_selector.setObjectName("stretch_selector")
        self.interval_selector = QComboBox(self)
        self.interval_selector.setObjectName("interval_selector")

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
        if self.action_run_sep is not None:
            self.action_run_sep.triggered.connect(self.run_sep_extract)
        if self.action_show_markers is not None:
            self.action_show_markers.triggered.connect(self._show_marker_dock)
        if self.action_append_frames is not None:
            self.action_append_frames.triggered.connect(self._append_frames)
        if self.marker_dock is not None:
            self.marker_dock.markers_updated.connect(self._apply_markers)
        if self.frame_player_dock is not None:
            self.frame_player_dock.frame_changed.connect(self._switch_frame)

    def apply_startup_request(self) -> None:
        """Apply the optional startup file request passed from `main.py`.

        Intended decision point:
        - no startup path: leave window empty
        - startup path provided: build `OpenFileRequest` and forward to `open_file_from_request()`
        """

        if self.initial_path:
            self.open_file_from_request(
                OpenFileRequest(path=self.initial_path, hdu_index=self.initial_hdu)
            )

    def open_file(self, path: str | None = None, hdu_index: int | None = None) -> None:
        """Open one or more FITS files (replaces existing frames).

        If path is None, a file dialog supporting multi-select is shown.
        """

        from ..core.fits_data import FITSData

        if not path:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Open FITS File(s)", "", "FITS Files (*.fits *.fit *.fts);;All Files (*)"
            )
            if not paths:
                return
        else:
            paths = [path]

        self._frames.clear()
        self._frame_images.clear()
        self._current_frame_index = 0

        for p in paths:
            try:
                data = FITSData.load(p, hdu_index)
                self._frames.append(data)
                self._frame_images.append(self._render_frame(data))
            except Exception as e:
                self.show_error("Open failed", f"{p}: {e}")

        if not self._frames:
            return

        self._activate_frame(0)
        self._sync_frame_player()

    def open_file_from_request(self, request: OpenFileRequest) -> None:
        """Structured wrapper around the public open-file entry point."""

        self.open_file(path=request.path, hdu_index=request.hdu_index)

    def close_current_file(self) -> None:
        """Close the current FITS file and reset the window state.

        Main flow:
        `MainWindow.close_current_file()` -> `FITSService.close_file()`
        -> clear canvas, table, dialog state, and status bar.
        """

        self.fits_service.close_file()
        self.current_catalog = None
        self._frames.clear()
        self._frame_images.clear()
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
        if self.sep_panel is not None:
            self.sep_panel.set_panel_state(self.build_sep_panel_state())
        if self.app_status_bar is not None:
            self.app_status_bar.clear_data()
        self.sync_render_controls()

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

    def build_render_control_state(self) -> RenderControlState:
        """Construct the toolbar render-control state from the FITS service."""

        has_data = self.fits_service.current_data is not None
        return RenderControlState(
            available_stretches=tuple(self.fits_service.AVAILABLE_STRETCHES),
            available_intervals=tuple(self.fits_service.AVAILABLE_INTERVALS),
            current_stretch=self.fits_service.current_stretch,
            current_interval=self.fits_service.current_interval,
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
        return [
            TableRowViewModel(row_index=i, values=row)
            for i, row in enumerate(catalog.to_rows())
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
        return CanvasImageState(
            width=width,
            height=height,
            has_image=True,
            feedback=ViewFeedbackState(status="ready"),
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

    def _apply_markers(self, coords: list) -> None:
        """Draw markers on the canvas from the marker dock."""

        if self.canvas is None or self.marker_dock is None:
            return
        self.canvas.set_markers(
            coords,
            radius=self.marker_dock.radius(),
            color=self.marker_dock.color(),
            line_width=self.marker_dock.line_width(),
        )

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
            self.current_catalog.to_csv(path)
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

        _ = params

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
            if self.fits_service.current_data is not None:
                self._rerender_all_frames()
                self._show_current_frame_image()

    def _handle_interval_changed(self, name: str) -> None:
        """Update the selected interval mode from the toolbar and re-render."""

        if name:
            self.fits_service.set_interval(name)
            if self.fits_service.current_data is not None:
                self._rerender_all_frames()
                self._show_current_frame_image()

    # --- Frame management ---

    def _render_frame(self, data: Any) -> QImage | None:
        """Render a FITSData to QImage using the current stretch/interval."""

        self.fits_service.current_data = data
        result = self.fits_service.render()
        if result.image_u8 is None:
            return None
        h, w = result.height, result.width
        qimage = QImage(result.image_u8.data, w, h, w, QImage.Format.Format_Grayscale8)
        return qimage.copy()

    def _rerender_all_frames(self) -> None:
        """Re-render all cached frame images with current stretch/interval."""

        for i, frame_data in enumerate(self._frames):
            self._frame_images[i] = self._render_frame(frame_data)
        if self._frames:
            self.fits_service.current_data = self._frames[self._current_frame_index]

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
            self.app_status_bar.clear_data()

    def _show_current_frame_image(self) -> None:
        """Push the cached QImage for the current frame into the canvas."""

        if self.canvas is None:
            return
        idx = self._current_frame_index
        if 0 <= idx < len(self._frame_images):
            img = self._frame_images[idx]
            self.canvas.set_image(img)
        else:
            self.canvas.clear_image()

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

    def _switch_frame(self, index: int) -> None:
        """Handle frame change signal from the player dock."""

        self._activate_frame(index)
        if self.frame_player_dock is not None:
            self.frame_player_dock.set_current_frame(index)

    def _append_frames(self) -> None:
        """Append additional FITS files to the frame list."""

        from ..core.fits_data import FITSData

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Append FITS Frame(s)", "", "FITS Files (*.fits *.fit *.fts);;All Files (*)"
        )
        if not paths:
            return

        for p in paths:
            try:
                data = FITSData.load(p)
                self._frames.append(data)
                self._frame_images.append(self._render_frame(data))
            except Exception as e:
                self.show_error("Append failed", f"{p}: {e}")

        if self._frames:
            self.fits_service.current_data = self._frames[self._current_frame_index]

        self._sync_frame_player()
