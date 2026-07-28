# Next-Step Todo

This file contains only active performance and product-quality work that remains after AstroView 1.10.0. Completed work belongs in `CHANGELOG.md` and release notes.

## Rendering and Playback
- Revisit whether full-resolution background render results should preserve zoom/viewport position more explicitly during fast frame switches.

## Data Loading
- Profile FITS files with real WCS payloads and compressed HDUs to see whether WCS construction or HDU scanning needs its own optimization path.
- Consider optional metadata-only preloading for large frame sets so playback can start before every frame is fully opened.
- Decide whether append-frame loading should surface a richer in-UI progress indicator than the current status-bar text.
- Consider a separately budgeted table-HDU viewer with pagination instead of treating table HDUs as image data.

## UI and UX
- Consider a project/session format that persists measurements, Region documents, comparison selections, and analysis parameters.

## Scientific Workflows and Interoperability
- Profile real distorted WCS data before considering an interpolation mode beyond the current bounded nearest-neighbour comparison path.
- Consider exporting aperture/ROI measurements with their parameters and frame identity for reproducible analysis.
- Consider optional Gaia-result caching or explicit cross-matching while keeping network and memory limits visible to the user.
- Evaluate additional DS9 shapes and true `physical` detector-coordinate transforms only when their metadata semantics can be validated reliably.

## Robustness and Testing
- Validate the packaged Windows moving-target spawn path in the 1.10.0 release artifact.
- Review frozen bundle size and safe trimming only inside a freshly prepared, exactly locked release environment.
- Add Authenticode signing for the Windows installer and executable; until then, continue publishing SHA-256 manifests and the explicit SmartScreen warning.
- Consider signed update metadata, an SBOM, and reproducible macOS/Linux packages after the Windows release path is stable.
