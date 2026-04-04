# Changelog

## Unreleased

### Added
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
