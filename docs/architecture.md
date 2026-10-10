# Application boundaries

AstroView keeps scientific computation independent of Qt. This document describes
the application boundaries introduced by the current refactor; it is not a plan
to replace the desktop toolkit or the FITS/SEP algorithms.

## State and ownership

- `core/` owns FITS data, scientific calculations, resource limits, pure image
  geometry and rendering contracts. It does not import the application layer.
- `app/frame_session.py` owns one `FrameState` per dataset, including its display
  texture, background/residual products, render validity and resolved display
  parameters. Appending and clearing a session cannot desynchronize cache arrays.
  Qt images belong here, not in the scientific model.
- Feature controllers own requests and worker lifetimes. `FileLoadController`
  coalesces repeated opens to the newest pending request. `ComparisonController`
  filters results against the selected pair. `SEPController` owns ROI validation,
  estimation, user-confirmation state and extraction after the previous worker
  retires. `MovingTargetController` retains its sequence/context checks. Views
  receive signals and presentation state.
- `MainWindow` creates and connects views/controllers, applies cross-feature
  policy, and handles dialogs. Render/background scheduling still lives here;
  future extraction should preserve its tested global worker limits.

`TaskLifecycle` separates result validity from physical worker ownership. Cancelling
immediately rejects queued callbacks, but the thread/worker slot is retained until
the matching thread stops. A late cleanup callback cannot retire a newer request.
All UI-facing relays are `QObject` slots owned by their GUI-thread controller.

## Scientific coordinates and display textures

`core/image_geometry.py` implements transpose/flip transforms and their inverses.
Pixel centers use `width - 1 - x`; half-open rectangle edges use `width - x`.
These are distinct operations and must remain so for ROI and region accuracy.

`ResolvedRenderSpec` is the immutable brightness mapping used by preview and full
render stages. Histogram ranges use the same resolution rules and, when available,
the cached mapping for the actual displayed data (original/background/residual).
Changing render preferences invalidates the mapping along with the render cache.
A late loader preview created with earlier preferences cannot seed a final render
with stale settings.

`RenderResult` carries a texture, original width/height, sample stride and mapping.
The normal desktop path keeps previews sampled. `ImagePixmapItem` paints this
texture in the original coordinate grid and clips the last sample block. Flips
include the cropped block offset, so odd dimensions remain aligned with overlays.
View preservation compares logical extents, not texture sizes, avoiding repeated
Qt viewport rounding when a preview is replaced by a full render.

`canvas_layers.py` owns source, catalog, region and measurement items and their
cleanup. `ImageCanvas` keeps interaction and viewport behavior. Raw export expands
only the raster on demand; annotated export paints the scene at logical dimensions.
Composite views paint each sampled texture directly into the combined image.

## Regression checks

Run the suite in the project's Conda environment:

```powershell
python -m unittest discover -s tests -v
```

Tests cover cancellation after signals have been queued, old cleanup callbacks,
thread occupancy after timeout, GUI-thread delivery, independent frame caches,
all eight image orientations, odd-sized sampled previews, raw/annotated exports,
and viewport stability across preview/full transitions. Existing scientific budgets
and wheel installation checks remain in place.

The synthetic preview benchmark compares the sampled and legacy expanded APIs in
one checkout. A 4096-by-4096 image with a 1024-pixel preview dimension produces a
1 MiB texture instead of 16 MiB. This is returned texture storage, not process RSS;
FITS I/O, WCS creation and Qt painting require separate end-to-end profiling.
