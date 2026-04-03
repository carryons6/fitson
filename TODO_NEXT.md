# Next-Step Todo

This file tracks the next performance and product-quality tasks worth doing after the current loading/rendering refactor.

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

## UI and UX
- ~~Add an explicit busy/loading indicator in the canvas for frames that are still rendering in the background.~~ Done.
- ~~Expose a user-facing preference for preview aggressiveness or maximum preview dimension.~~ Done.
- ~~Review whether frame-player controls should be temporarily throttled or visually annotated while a requested frame is still rendering.~~ Done.
- ~~Persist user preferences and workspace state such as stretch, interval, marker parameters, and window/dock layout.~~ Done.

## Robustness and Testing
- ~~Add integration-style Qt tests that exercise real `QThread` worker scheduling and signal delivery without relying only on mocked call paths.~~ Done.
- ~~Add regression tests around repeated stretch/interval changes while background renders are in flight.~~ Done.
- ~~Add tests for cancellation behavior when closing the window or opening a new file set during active background loading/rendering.~~ Done.
- Validate packaged Windows builds after the new worker-based rendering changes.
- Harden PyInstaller packaging so PySide6/numpy/conda runtime dependencies are collected reliably across environment variants, then review bundle size for safe trimming.
