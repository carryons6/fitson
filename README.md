# AstroView [English](README.md) | [简体中文](README_CN.md)

A desktop FITS astronomical image viewer built with PySide6.

## Features

### Image Display
- Open single or multiple FITS files with multi-HDU support
- Stretch modes: Linear, Log, Asinh, Sqrt
- Interval modes: ZScale, MinMax, 99.5%, 99%, 98%, 95%
- Mouse wheel zoom and left-click drag for panning
- Fit-to-window and actual-pixels (100%) view options
- View modes: original / SEP background / SEP residual, toggled with `F1` and `F2`; cached per frame and computed off the UI thread, with a `BKG` / `RESIDUAL` badge in the status bar and title
- Image orientation as a persistent display property: all 8 D4 transforms (flip H/V, rotate 90/180/270, transpose, anti-transpose) under `View → Image Orientation`, applied automatically to every loaded frame; an on-canvas compass shows the displayed-frame `+X` / `+Y` axes

### Source Extraction (SEP)
- Built-in SEP (Source Extractor Python) integration as an optional tool
- Full-image or ROI (right-click drag) source extraction
- Configurable extraction parameters (threshold, min area, deblend, etc.)
- Source overlay ellipses on the canvas with click-to-highlight and hover-to-preview
- Source catalog table with sortable columns; single-source extractions auto-select the result
- Cutout review with `Intensity`, `Background`, `Residual`, and `Connected Region` modes
- Tunable SEP background mesh (`bkg_box_size`, `bkg_filter_size`); changes invalidate the cached background and refresh the view
- Export catalog to CSV

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
- Each dock (source table, SEP params, markers, histogram, frame player) has a custom title bar with dock/undock and close buttons
- Floating docks gain native window controls (minimize / maximize / close) and behave as standalone windows

### Performance
- Memory-mapped FITS loading (`memmap=True`) for large files
- Deferred type conversion avoids unnecessary float32 copy at load time
- Subsampled interval calculation for large images (stride to ~1000x1000)
- Background multi-file FITS loading keeps the UI responsive during large imports
- Progressive first-frame preview rendering for faster time-to-first-image
- Background dirty-frame rendering to avoid blocking when switching frames

## Requirements

- Python 3.10+
- PySide6
- astropy
- numpy
- sep (optional, for source extraction)

Recommended install via conda-forge:
```bash
conda env create -f environment.yml
conda activate astroview
```

`environment.yml` pins `libblas` to the OpenBLAS variant so Windows PyInstaller
builds do not pull in the much larger MKL runtime set.

## Usage

You can launch AstroView from either the parent directory of `astroview/` or from the repository root itself:

```bash
python -m astroview                     # launch with empty window
python -m astroview path/to/image.fits  # open a FITS file directly
python -m astroview image.fits --hdu 1  # open a specific HDU
```

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

Windows bundle and installer:
```powershell
python -m pip install pyinstaller
.\scripts\build_windows.ps1
```

For the smallest Windows installer, build from an environment created via
`environment.yml`, which keeps NumPy on the OpenBLAS runtime.

## Architecture

- **`core/`**: domain logic (no Qt dependency)
  - `fits_data.py`: FITS loading, WCS, pixel sampling
  - `fits_service.py`: rendering pipeline, preview render helpers, normalization
  - `sep_service.py`: SEP source extraction wrapper
  - `source_catalog.py`: source catalog data model
  - `contracts.py`: typed dataclasses shared across layers

- **`app/`**: PySide6 UI layer
  - `main_window.py`: central coordinator between UI and services
  - `canvas.py`: QGraphicsView-based image display with overlays
  - `file_load_worker.py`: background FITS file loading worker
  - `frame_render_worker.py`: background frame rendering worker
  - `sep_panel.py`: SEP parameter form
  - `source_table.py`: source catalog table dock
  - `marker_dock.py`: coordinate marker input dock
  - `frame_player_dock.py`: multi-frame playback controls
  - `header_dialog.py`: FITS header viewer dialog
  - `status_bar.py`: cursor/zoom/frame status display

`MainWindow` is the sole coordinator: view modules emit signals and expose setters but never call services directly. Service modules return domain objects but never touch widgets.

## Recent Contributions

Recent GPT-5.4 contributions include:
- Windows packaging stabilization, including the restored `pydoc` dependency needed by `astropy` and verification that the rebuilt `AstroView.exe` starts correctly.
- Test-baseline expansion from placeholder coverage to executable unit tests for FITS loading, rendering, SEP extraction, source catalogs, background file loading, and background frame rendering.
- One-click Windows test runners under `tests/` for the conda `astro` environment.
- Startup compatibility so `python -m astroview` works from both the package parent directory and the repository root.
- Background multi-file FITS loading, progressive first-frame preview rendering, and background dirty-frame rendering to reduce UI stalls on large datasets.
- Image-orientation stabilization: fixed the runtime crash triggered by switching orientation on PySide6, aligned the displayed `QImage` transform with overlay/cursor coordinate remapping, and added regression coverage for all 8 supported orientations.

## Development Notes

- The initial project framing and high-level structure were shaped with GPT-5.4.
- The framework implementation and most feature work were then carried out with Claude Opus 4.6.
- Remaining implementation details, compatibility fixes, packaging work, performance work, and later refinements were completed with GPT-5.4.
