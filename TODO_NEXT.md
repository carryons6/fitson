# Next-Step Todo

This file tracks the next performance and product-quality tasks worth doing after AstroView 1.8.0.

## Completed in 1.8.0
- ~~Add bounded ROI statistics and circular-aperture photometry with background subtraction, SNR, centroid, and FWHM.~~ Done.
- ~~Add a bounded RA/Dec grid and cancellable Gaia DR3 cone-search overlay.~~ Done.
- ~~Add safe DS9 Region import/export, diagnostics, overlays, and ROI/aperture capture.~~ Done.
- ~~Add cancellable side-by-side, blink, and difference comparison with direct-pixel and restricted WCS alignment paths.~~ Done.
- ~~Apply feature-specific resource budgets and stale-result protection to the new measurement, catalog, Region, and comparison workflows.~~ Done.

## Rendering and Playback
- ~~Prewarm the next frame preview during playback so frame stepping and autoplay feel more continuous.~~ Done.
- ~~Add a small render queue/prioritization policy so the current frame always wins over stale background render requests.~~ Done.
- ~~Consider a multi-stage preview pipeline for very large images, such as 1024 px preview, then 2048 px preview, then full render.~~ Done.
- Revisit whether full-resolution background render results should preserve zoom/viewport position more explicitly during fast frame switches.
- ~~Preserve zoom level and viewport position more explicitly when switching frames or when a higher-quality render replaces a preview.~~ Done.

## Data Loading
- Profile FITS files with real WCS payloads and compressed HDUs to see whether WCS construction or HDU scanning needs its own optimization path.
- Consider optional metadata-only preloading for large frame sets so playback can start before every frame is fully opened.
- Decide whether append-frame loading should surface a richer in-UI progress indicator than the current status-bar text.
- Consider a separately budgeted table-HDU viewer with pagination instead of treating table HDUs as image data.

## UI and UX
- ~~Add an explicit busy/loading indicator in the canvas for frames that are still rendering in the background.~~ Done.
- ~~Expose a user-facing preference for preview aggressiveness or maximum preview dimension.~~ Done.
- ~~Review whether frame-player controls should be temporarily throttled or visually annotated while a requested frame is still rendering.~~ Done.
- ~~Persist user preferences and workspace state such as stretch, interval, marker parameters, and window/dock layout.~~ Done.
- Consider a project/session format that persists measurements, Region documents, comparison selections, and analysis parameters.

## Scientific Workflows and Interoperability
- Profile real distorted WCS data before considering an interpolation mode beyond the current bounded nearest-neighbour comparison path.
- Consider exporting aperture/ROI measurements with their parameters and frame identity for reproducible analysis.
- Consider optional Gaia-result caching or explicit cross-matching while keeping network and memory limits visible to the user.
- Evaluate additional DS9 shapes and true `physical` detector-coordinate transforms only when their metadata semantics can be validated reliably.

## Robustness and Testing
- ~~Add integration-style Qt tests that exercise real `QThread` worker scheduling and signal delivery without relying only on mocked call paths.~~ Done.
- ~~Add regression tests around repeated stretch/interval changes while background renders are in flight.~~ Done.
- ~~Add tests for cancellation behavior when closing the window or opening a new file set during active background loading/rendering.~~ Done.
- Validate packaged Windows builds after the 1.8.0 worker, WCS, catalog, Region, measurement, and comparison changes.
- Harden PyInstaller packaging so PySide6/numpy/conda runtime dependencies are collected reliably across environment variants, then review bundle size for safe trimming.
- Add Authenticode signing for the Windows installer and executable; until then, continue publishing SHA-256 manifests and the explicit SmartScreen warning.
- Consider signed update metadata, an SBOM, and reproducible macOS/Linux packages after the Windows release path is stable.
