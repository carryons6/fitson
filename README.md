# AstroView [English](README.md) | [简体中文](README_CN.md)

A desktop FITS astronomical image viewer built with PySide6.

## Features

### Image Display
- Open single or multiple FITS files with multi-HDU support
- Double-click the empty canvas, drag files onto it, or press `Ctrl+O` to open data
- Stretch modes: Linear, Log, Asinh, Sqrt
- Interval modes: ZScale, MinMax, 99.5%, 99%, 98%, 95%
- Mouse wheel zoom and left-click drag for panning
- Fit-to-window and actual-pixels (100%) view options
- View modes: original / SEP background / SEP residual, toggled with `F1` and `F2`; cached per frame and computed off the UI thread, with a `BKG` / `RESIDUAL` badge in the status bar and title
- Image orientation as a persistent display property: all 8 D4 transforms (flip H/V, rotate 90/180/270, transpose, anti-transpose) under `View → Image Orientation`, applied automatically to every loaded frame; an on-canvas compass shows the displayed-frame `+X` / `+Y` axes

### Source Extraction (SEP)
- Built-in SEP (Source Extractor Python) integration
- Full-image source extraction, or choose `ROI: Extract Sources` before right-dragging a region
- Configurable extraction parameters (threshold, min area, deblend, etc.)
- Source overlay ellipses on the canvas with click-to-highlight and hover-to-preview
- Source catalog table with sortable columns; single-source extractions auto-select the result
- Cutout review with `Intensity`, `Background`, `Residual`, and `Connected Region` modes
- Tunable SEP background mesh (`bkg_box_size`, `bkg_filter_size`); changes invalidate the cached background and refresh the view
- Export catalog to CSV

### Measurement Workbench
- `ROI: Measure` is the default right-drag task and reports finite/invalid pixel counts, minimum, maximum, mean, median, standard deviation, and sum
- Circular-aperture photometry with a configurable background annulus
- Background-subtracted net flux, robust background RMS, uncertainty, SNR, centroid, FWHM, and peak measurements
- In Measure mode, click the image to set the aperture center; panning no longer changes it, and ROI/aperture footprints remain visible as overlays
- NaN/Inf values are excluded and sampled areas are constrained by a configurable pixel budget

### WCS and Gaia DR3
- Optional projected RA/Dec grid with sexagesimal labels for celestial-WCS frames
- Cancellable Gaia DR3 cone search through the fixed ESA HTTPS TAP service; an internet connection is required
- Configurable search radius, maximum result count, and faint G-magnitude limit
- In-frame Gaia sources appear as selectable canvas overlays and table rows
- Grid geometry, catalog response size, row count, query radius, and query duration are bounded

### DS9 Region Interchange
- Import and export DS9 `.reg` files without evaluating commands or loading external resources
- Supports `image`, `physical`, `fk5`, and `icrs` coordinates with circle, box, ellipse, polygon, and point shapes; physical-region pixel values are displayed as image coordinates
- Region table, visibility toggle, import warning summary, and canvas overlays that follow image orientation; parser results retain line-level diagnostics for API callers
- Capture the current AstroView ROI or aperture into the active Region document
- Parsing and serialization enforce file-size, line, region, vertex, attribute, and numeric-value limits

### Image Comparison
- Select any two loaded frames as A and B
- Side-by-side, timed blink, and A-minus-B difference modes
- Direct pixel comparison for equal image shapes, with optional bounded nearest-neighbour WCS alignment onto frame A's grid
- A/B display rendering uses shared interval limits for a visually fair comparison
- Comparison preparation runs in a cancellable background worker and rejects stale results

### Coordinate Markers
- Draw circle markers on the image at specified coordinates
- Supports both pixel (x, y) and WCS (RA, Dec) coordinate input
- Single-coordinate add or batch input (one per line)
- Configurable radius, line width, and color

### Multi-Frame Playback
- Open multiple FITS files as an ordered frame sequence
- Append additional frames to an existing sequence
- Frame player dock with play/pause, FPS control, and loop/bounce modes
- Keyboard shortcuts: `[` previous frame, `]` next frame

### Moving Target Detection
- Analyze at least five equal-sized loaded frames through `Tools -> Moving Targets...`
- Capture a one-shot cross-frame ROI with right-drag, or use the full frame when it fits the resource budget
- Per-frame SEP extraction, robust stellar translation, temporal-median subtraction, static-source masking, and constant-velocity track fitting
- Prefer one consistent FITS timestamp convention (`DATE-AVG`, `MJD-AVG`, and similar); valid timestamps must be unique and strictly increasing in the loaded frame order
- Use an explicit fixed cadence when timestamps are unavailable, or deliberately disable header timing for an already ordered sequence
- Red circles show recovered SEP centroids when matched and fitted track predictions otherwise; they follow playback and image orientation
- Inspect hits, current position, velocity, speed, and fit RMS; export one target/frame row per observation to CSV
- Pure-translation registration rejects sequences with too few stellar matches or excessive residual RMS (for example, incompatible fields, rotation, or scale changes)
- The default 4,000,000-pixel ROI, 384 MiB sequence stack, 250,000 total SEP sources, and bounded intermediate-track budgets reject unsafe work

### Status Bar
- Real-time pixel coordinates and value under the cursor
- WCS RA/Dec display (when WCS is available)
- Current zoom level
- Frame counter for multi-frame sequences
- File-loading progress messages during background FITS import

### Header Viewer
- Full FITS header display in a searchable dialog
- Keyword filter for quick lookup

### Workspace
- Each dock (source table, SEP params, markers, histogram, frame player, measurement, moving targets, image comparison, DS9 Regions, and WCS/catalog) has a custom title bar with dock/undock and close buttons
- Floating docks gain native window controls (minimize / maximize / close) and behave as standalone windows

### Performance and safety
- Header-based allocation budgets are enforced before pixel decoding
- Decoded arrays are detached from file mappings when needed, so source files can be closed or overwritten safely on Windows
- Measurements, moving-target detection, image comparison, WCS grids, Gaia responses, and DS9 Region interchange use feature-specific resource budgets
- Gaia queries, moving-target analysis, and comparison rendering run outside the GUI thread and ignore cancelled or stale results
- WCS grids are generated on demand, bounded, and cached for reuse
- Subsampled interval calculation for large images (stride to ~1000x1000)
- Background multi-file FITS loading keeps the UI responsive during large imports
- Progressive first-frame preview rendering for faster time-to-first-image
- Background dirty-frame rendering to avoid blocking when switching frames

## Requirements

- Python 3.10+
- PySide6
- astropy
- numpy
- sep

Recommended install via conda-forge:
```bash
conda env create -f environment.yml
conda activate astroview
```

`environment.yml` is the human-maintained development specification and pins
`libblas` to OpenBLAS. Release CI instead consumes
`environment-win-64.conda.lock`, which fixes every direct and transitive Conda
artifact by URL, build, and SHA-256.

## Usage

From the repository root:

```bash
python -m astroview                     # launch with empty window
python -m astroview path/to/image.fits  # open a FITS file directly
python -m astroview image.fits --hdu 1  # open a specific HDU
```

After installing the wheel or running `python -m pip install .`, the
`astroview` console command is available from any directory.

### FITS resource limits

Untrusted FITS metadata is checked before Astropy materializes pixel data. The
desktop loader accepts at most `8192 × 8192` total pixels, 512 MiB of estimated
decoded data, and 4096 frames by default. Library callers may explicitly raise
or disable individual limits for trusted data.

FITS tile compression (`CompImageHDU`) remains supported and is checked against
the same decoded-size budget. Whole-file gzip/ZIP/bzip2/xz/LZW wrappers are
rejected before decompression; safely decompress those files first.

### Windows release installer

Download `AstroView_Setup_1.10.0.exe` and `SHA256SUMS.txt` from the
[GitHub Releases page](https://github.com/carryons6/fitson/releases). The
Windows installer is **not Authenticode-signed**, so Windows SmartScreen may
display a warning. Verify the installer against the release checksum before
running it.

## Testing

The project test baseline is expected to run in an activated environment created from `environment.yml`.

One-click runners:
```powershell
.\tests\run_tests.bat
.\tests\run_tests.ps1
```

Direct unittest run:
```powershell
python -m unittest discover -s tests -v
```

## Build

Windows bundle and installer from the exact release environment:
```powershell
.\scripts\prepare_release_env.ps1
conda activate astroview-release
.\scripts\build_windows.ps1 -CondaLockPath environment-win-64.conda.lock
```

The preparation script leaves an already matching environment unchanged. If an
environment named `astroview-release` exists but differs from the lock, it fails
without modifying it; rerun with `-Recreate` only when you deliberately want to
remove and rebuild that release-only environment. The lock keeps NumPy on
OpenBLAS, and both preparation and build reject an explicit URL+SHA package set
that differs from it. They also reject unlocked pip packages, verify Conda-owned
files are neither altered nor missing, and run `pip check`. GitHub Actions also
downloads fixed Miniforge and Inno Setup installers and verifies their SHA-256
hashes before using them.

## Architecture

- **`core/`**: domain logic (no Qt dependency)
  - `fits_data.py`: FITS loading, WCS, pixel sampling
  - `fits_service.py`: rendering pipeline, preview render helpers, normalization
  - `measurement_service.py`: bounded ROI statistics and aperture photometry
  - `wcs_grid.py`: bounded RA/Dec grid projection
  - `catalog_service.py`: validated Gaia DR3 TAP queries and response parsing
  - `ds9_regions.py`: safe DS9 Region parsing and serialization
  - `image_comparison.py`: bounded pixel/WCS comparison and difference output
  - `moving_targets.py`: bounded registration, temporal differencing, and linear-track recovery
  - `sep_service.py`: SEP source extraction wrapper
  - `source_catalog.py`: source catalog data model
  - `contracts.py`: typed dataclasses shared across layers

- **`app/`**: PySide6 UI layer
  - `main_window.py`: composition root for UI, controllers, workers, and services
  - `canvas.py`: QGraphicsView-based image display with overlays
  - `file_load_worker.py`: background FITS file loading worker
  - `frame_render_worker.py`: background frame rendering worker
  - `sep_panel.py`: SEP parameter form
  - `source_table.py`: source catalog table dock
  - `marker_dock.py`: coordinate marker input dock
  - `frame_player_dock.py`: multi-frame playback controls
  - `measurement_dock.py`: ROI statistics and aperture-photometry controls
  - `catalog_overlay_dock.py`: WCS-grid and Gaia-query controls
  - `ds9_region_dock.py`: DS9 Region import/export and document controls
  - `comparison_dock.py`: frame A/B comparison and blink controls
  - `moving_target_dock.py`: cross-frame ROI, detection controls, and trajectory table
  - `moving_target_controller.py`: moving-target state, request identity, and worker lifecycle
  - `moving_target_worker.py`: cancellable subprocess adapter for SEP-heavy sequence analysis
  - `header_dialog.py`: FITS header viewer dialog
  - `status_bar.py`: cursor/zoom/frame status display

`MainWindow` remains the cross-feature composition root, while focused controllers
own feature-local state and worker lifecycles. View modules emit signals and expose
setters but never call services directly; service modules return domain objects and
never touch widgets.

## Recent Contributions

Recent GPT-5.4 contributions include:
- Windows packaging stabilization, including the restored `pydoc` dependency needed by `astropy` and verification that the rebuilt `AstroView.exe` starts correctly.
- Test-baseline expansion from placeholder coverage to executable unit tests for FITS loading, rendering, SEP extraction, source catalogs, background file loading, and background frame rendering.
- One-click Windows test runners under `tests/` for the conda `astro` environment.
- Startup compatibility for `python -m astroview` from the repository root and the installed `astroview` console command.
- Background multi-file FITS loading, progressive first-frame preview rendering, and background dirty-frame rendering to reduce UI stalls on large datasets.
- Image-orientation stabilization: fixed the runtime crash triggered by switching orientation on PySide6, aligned the displayed `QImage` transform with overlay/cursor coordinate remapping, and added regression coverage for all 8 supported orientations.

## Development Notes

- The initial project framing and high-level structure were shaped with GPT-5.4.
- The framework implementation and most feature work were then carried out with Claude Opus 4.6.
- Remaining implementation details, compatibility fixes, packaging work, performance work, and later refinements were completed with GPT-5.4.
