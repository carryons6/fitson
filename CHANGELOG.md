# Changelog

## Unreleased

## 1.4.0 - 2026-04-15

### Added
- Added a resettable, versioned workspace layout with safer screen-geometry restore so saved dock/window state no longer reopens off-screen or with unusable proportions on different displays.
- Added richer source inspection on the right side of the workspace, including a dedicated `Cutout` tab, a compact field/value details panel, and clearer high-contrast empty states for the cutout preview.
- Added a custom magnifier cursor plus subpixel coordinate sampling so the magnifier label now reports meaningful two-decimal pixel positions instead of staying pinned to integer values.

### Changed
- Reworked the default dock arrangement so `Source Table`, `SEP Params`, and `Markers` share the right-side tab stack while `Frame Player` stays below, improving space usage on narrower and 3:2 displays.
- Changed the source-table inspector to adapt its internal splitter layout by dock area, keeping the table, details, and cutout preview visible without forcing the cutout below the screen edge.
- Changed canvas empty/loading feedback and cutout placeholder messaging to use high-contrast cards so guidance stays legible over dark imagery and dark-theme panels.

### Fixed
- Fixed blurry cutout previews after the dock refactor by restoring a sharper scaling path for the preview image.
- Fixed repeated `QWindowsWindow::setGeometry` restore warnings on Windows by validating saved screen metadata before applying stored window geometry.
- Fixed low-visibility guidance in the main canvas and cutout preview where onboarding and rendering messages could disappear against dark backgrounds.
- Fixed packaged Windows builds missing `FileVersion` / `ProductVersion` metadata on `AstroView.exe`.
- Fixed packaged `AstroView.exe` failing at startup with `Importing the numpy C-extensions failed` by collecting the minimal MKL runtime DLLs (`mkl_rt`, `mkl_core`, `mkl_intel_thread`, `mkl_def`, `mkl_avx2`, `mkl_vml_*`) required by `libcblas.dll` and registering the bundle's `_internal` directories as Windows DLL search paths.

### Validated
- Verified the updated canvas, source-table, and main-window workflows with `python -m unittest tests.test_canvas tests.test_source_table tests.test_main_window_loading -v` (`97` tests passed).
- Verified the Windows packaging flow with `.\scripts\build_windows.ps1 -SkipTests`, producing `installer_output\AstroView_Setup_1.4.0.exe`.

## 1.3.1 - 2026-04-11

### Added
- Added FITS drag-and-drop open support on both the main window and canvas, plus a more actionable empty-canvas onboarding state that advertises file open, drag-and-drop, zoom, and ROI extraction.
- Added a persistent status-task area for long-running work so file loading, SEP extraction, and related failures stay visible without forcing users to watch the transient status-bar text.
- Added explicit recenter affordances for the currently selected source: pressing `Enter` in the source table, re-clicking the active row, or double-clicking the cutout preview now recenters the target on the canvas.
- Added recent-file history and a `Reopen Last Session` action so successful frame sequences can be reopened from the File menu without rebuilding the same session by hand.
- Added case-sensitive header filtering, invalid-line reporting for batch marker input, and targeted tests covering the new status bar, header dialog, and source-table behaviors.

### Changed
- Changed source-table selection behavior so picking a source automatically recenters the canvas, and the cutout preview now advertises its double-click recenter shortcut.
- Changed frame-player controls to display user-facing frame numbers as 1-based while preserving the existing internal 0-based indexing.
- Changed source-table sorting to use typed numeric ordering instead of string ordering, and expanded filtering to support `field:value` queries for direct metric filtering.

### Fixed
- Fixed SEP parameter edits leaving the previous catalog looking current; result views now show an explicit stale/outdated state until extraction is rerun.
- Fixed marker batch parsing silently dropping invalid rows by surfacing concrete line-level input errors instead.
- Fixed repeated source recentering workflows that previously required selecting a different target first before the same source could be centered again.

### Validated
- Verified the updated UI workflow in the `astro` environment with `D:\Miniforge\envs\astro\python.exe -m unittest tests.test_source_table tests.test_marker_dock tests.test_header_dialog tests.test_main_window_loading tests.test_frame_player_dock tests.test_canvas tests.test_status_bar` (`100` tests passed).

## 1.3.0 - 2026-04-10

### Fixed
- Fixed critical bug where multi-frame playback (e.g. 15 frames) crashed the application after ~1 minute due to unbounded render thread accumulation. Frame renders during playback now use preview-only mode, eliminating thread pile-up.
- Fixed "Rendering Full Frame" indicator staying visible indefinitely during playback even though frames were displaying correctly.

### Added
- Added a background render queue that automatically renders all frames at full resolution during playback. Frames display instantly using fast previews; once the queue completes, playback runs entirely from cache with zero latency.

## 1.2.9 - 2026-04-10

### Added
- Added a magnifier overlay (`F1` toggle): 200×200 floating lens that follows the cursor, showing a zoomed pixel view with crosshair and pixel coordinates. Magnification (2–16×, default 4×) is relative to the current canvas zoom level and adjustable from the toolbar spinbox. Cursor switches to crosshair while the magnifier is active.

### Changed
- Unified background/residual view mode switching from two separate shortcuts (`F1`/`F2`) into a single `Tab` key that cycles original → background → residual → original.

### Fixed
- Fixed Tools → SEP Extract unexpectedly popping up the Histogram dock and freezing the UI while paging in the full image. `run_sep_extract` no longer force-shows the histogram dock.
- Fixed `_refresh_histogram_view` running a full-image `nanmin/nanmax/histogram` pass on the UI thread even when the Histogram dock was hidden. The refresh now short-circuits while the dock is invisible and lazily recomputes via `visibilityChanged` the first time the user opens it, eliminating hidden stalls on startup, file load, and frame switches.
- Fixed the window title bar not showing a computing indicator when switching to BKG/Residual view while the background is still being computed; the title now appends "计算中..." and clears it when the computation finishes.

## 1.2.8 - 2026-04-08

### Added
- Added a SEP background / residual view mode toggle: `F1` switches between original and background, `F2` between original and residual; both modes share a per-frame cache so toggling is instant after the first compute.
- Added asynchronous background computation via `app/frame_bkg_worker.py` so SEP background extraction never blocks the UI; the status bar shows `正在计算背景...` while a worker runs and adjacent frames are pre-warmed for smoother stepping.
- Added `SEPService.compute_background()` as the single entry point for SEP background/residual computation, with new `bkg_box_size` and `bkg_filter_size` parameters exposed in the SEP panel; changing either invalidates the cached background and triggers a re-render.
- Added a persistent view-mode badge (`BKG` / `RESIDUAL`) in the status bar plus a `[BKG]` / `[RESIDUAL]` suffix in the window title so the active view is always visible.
- Added `Background` and `Residual` cutout-review modes that slice from the same cached background/residual frames used by the main view.
- Added auto-selection of the only source after a SEP extraction returns exactly one record, so the canvas highlight, table row, and cutout preview update without an extra click.
- Added a hover-to-highlight signal in the source table: hovering a row temporarily highlights the corresponding source on the canvas without disturbing the click selection or cutout preview.
- Added a custom dock title bar with dock/undock and close buttons; floating docks now also gain native minimize / maximize / close window controls so each panel can be used as a standalone window.
- Added an image-orientation property with all 8 D4 transforms (identity, flip H/V, rotate 90/180/270, transpose, anti-transpose) under `视图 → 图像方向`. Orientation is persisted via `QSettings` (`view/orientation`) and applied as the primary display property: every loaded frame is presented in the chosen orientation from the start.
- Added `app/compass_overlay.py`, a small `CompassOverlay` widget anchored to the canvas top-right that paints the displayed-frame directions of the original `+X` and `+Y` axes and updates whenever the orientation changes.

### Changed
- `MainWindow._render_data_for_index()` is now cache-only and never blocks the UI thread on SEP computation; cache misses dispatch a `FrameBkgWorker` and the canvas updates when the result lands.
- `_invalidate_bkg_caches()` centralizes background/residual cache invalidation, cancels in-flight workers, and re-renders only the frames that actually depend on the cache.
- `ImageCanvas.draw_sources()` now consults an optional position-transform callable so source overlays follow the active orientation while the underlying catalog stays in original-image coordinates.
- Cursor sampling and ROI extraction now inverse-map displayed coordinates back to the original frame, so SEP, cutout, header, and pixel-value lookups always operate on the unrotated data regardless of the active view mode or orientation.
- Closing a file resets the view mode to original, clears the orientation badge, and cancels any in-flight background workers.

### Fixed
- Fixed a crash when switching image orientation on PySide6 builds where `QImage.mirrored()` rejects keyword arguments; orientation changes now use a Qt-compatible transform path.
- Fixed oriented frame rendering so the displayed `QImage` transform matches the catalog/cursor coordinate mapping for all 8 supported D4 orientations.
- Added regression coverage for all 8 image-orientation transforms so future orientation refactors do not reintroduce display/coordinate mismatches.

## 1.2.7 - 2026-04-07

### Added
- Added `app/theme.py` providing Fusion-based light and dark themes with full QSS coverage (menus, toolbars, docks, buttons, inputs, tables, scrollbars, tabs, sliders, progress bars).
- Added a `视图 → 主题` submenu with `浅色 / 深色` exclusive switching; the selection is persisted via `QSettings` under `ui/theme` and restored on next launch. Default theme is light.
- Added runtime-generated chevron arrow icons for `QSpinBox` / `QDoubleSpinBox`, rendered with `QPainter` to PNG in a temp cache directory and referenced from QSS for reliable cross-DPI display.
- Added a `Connected Region` view in cutout review so the selected source's segmentation region can be inspected directly.

### Changed
- `main.py` now applies the saved theme immediately after creating the `QApplication`.
- Removed the hard-coded global font size from the stylesheet so fonts follow the system setting and scale correctly on high-DPI displays.
- Widened spinbox up/down buttons with distinct hover/pressed states and a separator between them for clearer interaction affordance.

### Fixed
- Fixed packaged app version reporting so rebuilt installers no longer ship an older bundled app version.
- Fixed Windows packaged startup failures by collecting the required PySide6/Shiboken runtime DLLs and NumPy 2.4 modules.

### Validated
- Verified source table, source catalog, SEP, and main-window loading tests for the connected-region cutout workflow.
- Verified the rebuilt frozen Windows app starts successfully after the packaging fixes.

## 1.2.6 - 2026-04-06

### Added
- Added `VERSION`, `setup.py`, `pyproject.toml`, `MANIFEST.in`, and `environment.yml` so the project has explicit metadata, a reproducible environment definition, and a single version source.
- Added `scripts/build_windows.ps1` and GitHub Actions workflows for automated tests and Windows release builds.
- Added runtime file logging and unhandled-exception hooks so unexpected GUI failures leave a diagnostic trail for support.
- Added `tests/run_tests.ps1` and `tests/run_tests.bat` for one-click test execution in the conda `astro` environment.
- Added `app/file_load_worker.py` for background multi-file FITS loading.
- Added `app/frame_render_worker.py` for background frame rendering with progressive preview/full-resolution updates.
- Added `app/histogram_dock.py` to expose image histograms and manual display-range controls in the UI.
- Added `app/sep_extract_worker.py` so SEP source extraction runs off the UI thread.
- Added a `Check for Updates...` action in the Help menu with a background GitHub release/tag check worker.
- Added targeted tests for background file loading, background frame rendering, and main-window loading/render scheduling.
- Added a repository-root compatibility launcher so `python -m astroview` works from both the package parent directory and the repository root.
- Added shared render helpers in `core/fits_service.py` for full-resolution and low-resolution preview rendering.
- Added a source-detail panel with per-target field inspection and cutout preview in the `Source Table` dock.
- Added canvas-to-table source selection sync so double-clicking a source overlay selects the matching row in `Source Table`.

### Changed
- Changed package metadata and installer versioning to read from the repository `VERSION` file instead of repeating literal version strings.
- Changed test and build workflows to prefer the active Python environment rather than hard-coded local Miniforge paths.
- Expanded the test baseline from a handful of partial tests to a broader executable suite covering FITS loading, rendering, SEP, source catalogs, file loading, and frame rendering.
- Moved multi-file FITS loading off the UI thread to keep the main window responsive while importing large datasets.
- Changed first-image presentation to use a fast preview-first strategy before full-resolution rendering completes.
- Changed dirty-frame activation and frame switching to use background rendering instead of synchronous UI-thread rendering.
- Changed display defaults for newly opened FITS files to `Stretch=Linear` and `Interval=ZScale`.
- Changed the rendering pipeline to support manual interval limits alongside the existing stretch/interval presets.
- Changed extracted source tables to always expose `ID`, `X`, and `Y`, with persistent sorting/filtering state and richer source metrics such as `NPix` and `BkgRMS`.
- Changed source export workflow to standardize on CSV, with the former `Ctrl+Shift+E` region-export shortcut now routed to the same CSV export action.
- Changed the main window title to show the current application version and fixed packaged FITS loading for non-contiguous preview buffers that previously left the window blank after `Open`.
- Changed the update checker to bypass system proxy settings and fixed packaged HTTPS support by bundling the required SSL runtime files.
- Updated the README to document the current startup behavior, test workflow, architecture additions, and recent GPT-5.4 contributions.

### Validated
- Verified the test suite in the conda `astro` environment with `python -m unittest discover -s tests -v`.
- Verified large-sample responsiveness against `tests/data` with background loading, progressive first-frame rendering, and background frame switching.
