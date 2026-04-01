# AstroView

Current status: skeleton window runnable.

The application can be launched with `python -m astroview` (or `python main.py`).
The empty window displays menus, toolbar, dock panels, and status bar, but file-open
and all business logic remain unimplemented.

Qt toolkit: **PySide6** (via conda-forge `qt6-main` + `pyside6`).

This directory follows the Phase 1 design document and currently contains:

- UI layer modules for the main window, canvas, source table, header dialog, SEP panel, and status bar.
- Core layer modules for FITS data, FITS service, SEP service, and source catalog.
- Placeholder tests and dependency definitions.

## Interface notes

The codebase is currently organized around typed contracts rather than behavior:

- `core/contracts.py` defines request/state/result objects shared across modules.
- `MainWindow` is the only coordinator allowed to call both UI modules and core services.
- View modules emit signals or expose passive setters; they do not call services directly.
- Service modules return domain or render objects; they do not manipulate widgets directly.

## Planned call flow

Open file flow:
- `main.py` builds an `OpenFileRequest`.
- `MainWindow.open_file_from_request()` forwards to `MainWindow.open_file()`.
- `MainWindow.open_file()` calls `FITSService.open_file()` and then `refresh_image()`.
- `MainWindow.refresh_image()` calls `FITSService.render()` and pushes the result into `ImageCanvas`.

ROI extraction flow:
- `ImageCanvas` emits `roi_selected(x0, y0, width, height)`.
- `MainWindow.handle_roi_selected()` builds an `ROISelection`.
- `MainWindow` slices the image data and calls `SEPService.extract_from_roi()`.
- `MainWindow` forwards the returned `SourceCatalog` to `ImageCanvas` and `SourceTableDock`.

Cursor/status flow:
- `ImageCanvas` emits `mouse_moved(x, y)`.
- `MainWindow.update_status_from_cursor()` asks `FITSData` for a `PixelSample`.
- `MainWindow` forwards the sample to `AppStatusBar`.

## MainWindow assembly plan

Window bootstrap order:
- `MainWindow.initialize()`
- `configure_window_shell()`
- `build_ui()`
- `create_actions()`
- `connect_signals()`
- `apply_startup_request()`

UI assembly responsibilities:
- `build_central_canvas()` owns the central `ImageCanvas`.
- `build_docks()` owns `SourceTableDock` and `SEPParamsPanel`.
- `build_status_bar()` owns `AppStatusBar`.
- `build_menu_bar()` organizes File/View/Tools/Help menus.
- `build_tool_bar()` organizes file/view actions plus stretch and interval controls.

Signal binding responsibilities:
- `bind_canvas_signals()` connects cursor, ROI, and zoom events.
- `bind_source_table_signals()` connects row selection events.
- `bind_sep_panel_signals()` connects parameter changes.
- `bind_toolbar_signals()` connects render controls.
- `bind_action_triggers()` connects menu/toolbar actions to controller methods.

## UI module contracts

Canvas contract:
- `ImageCanvas` owns `CanvasImageState`, `CanvasOverlayState`, and `ZoomState`.
- The window coordinator pushes image and overlay state into the canvas.
- The canvas emits primitive Qt signals, but can also accept structured `ROISelection` and `ZoomState`.

Source table contract:
- `SourceTableDock` owns `TableColumnSpec`, `TableRowViewModel`, and `TableSelectionState`.
- Column definitions are configured once during assembly.
- Row view models are supplied by `MainWindow`, not built inside the table.

SEP panel contract:
- `SEPParamsPanel` owns `SEPFieldSpec` metadata and a typed `SEPParameters` object.
- Field specs define labels, control kinds, defaults, and limits.
- The panel emits typed parameter state but does not invoke `SEPService`.

Header dialog contract:
- `HeaderDialog` owns `HeaderFilterState`.
- Raw header text is pushed in by `MainWindow`.
- Search/filter state stays local to the dialog.

Status bar contract:
- `AppStatusBar` receives `PixelSample` and `ZoomState`.
- It acts as a passive sink for coordinator-provided state.

## Empty and disabled states

The UI contract now treats empty/error/disabled state as explicit data:

- `ViewFeedbackState` is the common payload for empty, ready, disabled, and error feedback.
- `ControlEnablementState` carries enabled/disabled state plus the reason text.
- `TableViewState`, `HeaderViewState`, and `SEPPanelState` wrap module-specific state with feedback.
- `RenderControlState` includes `disabled_reason` so toolbar controls can reflect why they are inactive.
- `MainWindow` is responsible for building these states through helper methods such as
  `build_empty_image_feedback()`, `build_empty_catalog_feedback()`, `build_no_header_feedback()`,
  `build_disabled_sep_feedback()`, and `build_error_feedback()`.
