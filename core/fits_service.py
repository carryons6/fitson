from __future__ import annotations

import operator
from typing import Any

import numpy as np

from .contracts import RenderRequest, RenderResult, ResolvedRenderSpec
from .fits_data import DEFAULT_MAX_PIXELS, FITSData, HDUInfo, open_fits_container


DEFAULT_MAX_PREVIEW_OUTPUT_PIXELS = DEFAULT_MAX_PIXELS


def _astropy_visualization():
    """Lazy import for astropy.visualization; deferred to first render call."""

    from astropy.visualization import (
        AsinhStretch,
        LinearStretch,
        LogStretch,
        MinMaxInterval,
        SqrtStretch,
        ZScaleInterval,
    )

    return {
        "AsinhStretch": AsinhStretch,
        "LinearStretch": LinearStretch,
        "LogStretch": LogStretch,
        "MinMaxInterval": MinMaxInterval,
        "SqrtStretch": SqrtStretch,
        "ZScaleInterval": ZScaleInterval,
    }


class FITSService:
    """FITS loading and display configuration service.

    Service contract:
    - Input: file path, HDU index, render configuration.
    - Output: `FITSData` for domain state and `RenderResult` for display state.
    - Consumer: `MainWindow`.
    """

    AVAILABLE_STRETCHES = ("Linear", "Log", "Asinh", "Sqrt")
    AVAILABLE_INTERVALS = ("ZScale", "MinMax", "Original", "Manual", "99.5%", "99%", "98%", "95%")

    def __init__(self) -> None:
        self.current_data: FITSData | None = None
        self.current_stretch = self.AVAILABLE_STRETCHES[0]
        self.current_interval = self.AVAILABLE_INTERVALS[0]
        self.manual_interval_limits: tuple[float, float] | None = None

    def list_image_hdus(self, path: str) -> list[HDUInfo]:
        """Inspect a FITS file and list image HDUs.

        Expected caller: `MainWindow.open_file()` before HDU selection UI.
        """

        from .fits_data import _scan_image_hdus

        with open_fits_container(path, memmap=True) as hdul:
            return _scan_image_hdus(hdul)

    def open_file(self, path: str, hdu_index: int | None = None) -> FITSData:
        """Open a FITS file and store it as the active dataset.

        Expected flow:
        `MainWindow.open_file()` -> `FITSService.open_file()` -> `FITSData.load()`.
        """

        self.current_data = FITSData.load(path, hdu_index)
        return self.current_data

    def close_file(self) -> None:
        """Release the current FITS dataset.

        Expected caller: `MainWindow.close_current_file()`.
        """

        self.current_data = None

    def set_stretch(self, name: str) -> None:
        """Update the active stretch mode.

        Expected caller: stretch control in `MainWindow`.
        """

        self.current_stretch = name

    def set_interval(self, name: str) -> None:
        """Update the active interval mode.

        Expected caller: interval control in `MainWindow`.
        """

        self.current_interval = name

    def set_manual_interval_limits(self, low: float, high: float) -> None:
        """Store explicit display limits used by the Manual interval mode."""

        low_value = float(low)
        high_value = float(high)
        if not np.isfinite(low_value) or not np.isfinite(high_value):
            raise ValueError("Manual interval limits must be finite numbers.")
        if high_value <= low_value:
            raise ValueError("Manual interval high limit must be greater than low limit.")
        self.manual_interval_limits = (low_value, high_value)

    def clear_manual_interval_limits(self) -> None:
        """Clear any explicit Manual interval limits."""

        self.manual_interval_limits = None

    def build_render_request(self) -> RenderRequest:
        """Build a render request from the current service configuration."""

        return RenderRequest(
            stretch_name=self.current_stretch,
            interval_name=self.current_interval,
            manual_vmin=None if self.manual_interval_limits is None else self.manual_interval_limits[0],
            manual_vmax=None if self.manual_interval_limits is None else self.manual_interval_limits[1],
        )

    def resolve_render_spec(
        self,
        data: FITSData | None = None,
        request: RenderRequest | None = None,
    ) -> ResolvedRenderSpec:
        """Resolve the active controls once for rendering and histogram display."""

        target = self.current_data if data is None else data
        request = request or self.build_render_request()
        manual_limits = None
        if request.manual_vmin is not None and request.manual_vmax is not None:
            manual_limits = (request.manual_vmin, request.manual_vmax)
        return resolve_render_spec(
            target,
            request.stretch_name,
            request.interval_name,
            manual_limits=manual_limits,
        )

    def render(
        self,
        request: RenderRequest | None = None,
        *,
        resolved_spec: ResolvedRenderSpec | None = None,
    ) -> RenderResult:
        """Render the active FITS dataset to a display-oriented 8-bit result.

        Expected flow:
        `MainWindow.refresh_image()` -> `FITSService.render()` -> `ImageCanvas.set_image()`.
        """

        if self.current_data is None or self.current_data.data is None:
            return RenderResult(image_u8=None)
        spec = resolved_spec or self.resolve_render_spec(request=request)
        return render_frame(self.current_data, spec)

    def finite_data_range(self, data: FITSData | None = None) -> tuple[float, float] | None:
        """Return the finite numeric range of the current image data."""

        target = self.current_data if data is None else data
        if target is None or target.data is None:
            return None

        finite = _finite_sample(target.data)
        if finite.size == 0:
            return None

        return float(np.nanmin(finite)), float(np.nanmax(finite))

    def histogram(
        self,
        data: FITSData | None = None,
        *,
        bins: int = 256,
        limits: tuple[float, float] | None = None,
        resolved_spec: ResolvedRenderSpec | None = None,
    ) -> tuple[np.ndarray, float, float]:
        """Return histogram counts and numeric range for the current image.

        When ``limits`` is provided, only finite pixel values within the
        inclusive ``[low, high]`` interval contribute to the histogram, and
        the returned range reflects those limits rather than the raw data
        extent. This is used to restrict the histogram view to the span of
        the active interval (e.g. ZScale or a manual range).
        Pass ``resolved_spec`` to use the exact range of a rendered frame.
        """

        if resolved_spec is not None:
            if limits is not None:
                raise ValueError("Pass either limits or resolved_spec, not both.")
            limits = resolved_spec.limits
            if limits is None:
                return np.zeros(bins, dtype=np.int64), 0.0, 0.0

        target = self.current_data if data is None else data
        if target is None or target.data is None:
            return np.zeros(bins, dtype=np.int64), 0.0, 0.0

        finite = _finite_sample(target.data)
        if finite.size == 0:
            if limits is not None:
                return np.zeros(bins, dtype=np.int64), float(limits[0]), float(limits[1])
            return np.zeros(bins, dtype=np.int64), 0.0, 0.0

        if limits is not None:
            low, high = float(limits[0]), float(limits[1])
            if high < low:
                low, high = high, low
            finite = finite[(finite >= low) & (finite <= high)]
            if finite.size == 0 or high <= low:
                counts = np.zeros(bins, dtype=np.int64)
                if high == low:
                    counts[0] = int(finite.size)
                return counts, low, high
            counts, _edges = np.histogram(finite, bins=bins, range=(low, high))
            return counts.astype(np.int64, copy=False), low, high

        min_value = float(np.nanmin(finite))
        max_value = float(np.nanmax(finite))
        if max_value <= min_value:
            counts = np.zeros(bins, dtype=np.int64)
            counts[0] = int(finite.size)
            return counts, min_value, max_value

        counts, _edges = np.histogram(finite, bins=bins, range=(min_value, max_value))
        return counts.astype(np.int64, copy=False), min_value, max_value

    def current_interval_limits(self, data: FITSData | None = None) -> tuple[float, float] | None:
        """Return the effective ``[vmin, vmax]`` for the active interval on the given data."""

        return self.resolve_render_spec(data).limits

    def header_text(self) -> str:
        """Return the active header as plain text.

        Expected flow:
        `MainWindow.show_header_dialog()` -> `FITSService.header_text()` -> `HeaderDialog.set_header_text()`.
        """

        if self.current_data is None:
            return ""
        return self.current_data.header_as_text()

    def current_wcs(self) -> Any:
        """Return the active WCS object."""

        if self.current_data is None:
            return None
        return self.current_data.get_wcs()


def render_image_u8(
    data: FITSData,
    stretch_name: str,
    interval_name: str,
    *,
    manual_limits: tuple[float, float] | None = None,
    resolved_spec: ResolvedRenderSpec | None = None,
) -> np.ndarray | None:
    """Render a FITSData object to an 8-bit grayscale numpy image."""

    spec = resolved_spec or resolve_render_spec(
        data, stretch_name, interval_name, manual_limits=manual_limits
    )
    return render_frame(data, spec).image_u8


def resolve_render_spec(
    data: FITSData | None,
    stretch_name: str,
    interval_name: str,
    *,
    manual_limits: tuple[float, float] | None = None,
) -> ResolvedRenderSpec:
    """Resolve a frame's brightness mapping without retaining its pixel array."""

    return ResolvedRenderSpec(
        stretch_name=stretch_name,
        interval_name=interval_name,
        limits=compute_interval_limits(data, interval_name, manual_limits=manual_limits),
    )


def render_frame(data: FITSData, spec: ResolvedRenderSpec) -> RenderResult:
    """Apply a resolved mapping without recomputing intervals or changing data."""

    if data.data is None:
        return RenderResult(image_u8=None, resolved_spec=spec)
    pixels = data.data
    height, width = pixels.shape[:2]
    if spec.limits is None or spec.limits[1] <= spec.limits[0]:
        image_u8 = np.zeros((height, width), dtype=np.uint8)
    else:
        vmin, vmax = spec.limits
        # Work on a copy; display normalization must never mutate scientific data.
        fdata = pixels.astype(np.float32, copy=True)
        np.clip(fdata, vmin, vmax, out=fdata)
        fdata -= vmin
        fdata /= vmax - vmin
        fdata = _build_stretch(spec.stretch_name)(fdata)
        np.multiply(fdata, 255, out=fdata)
        # NaNs have no display intensity. A single mask avoids the three
        # full-image masks that nan_to_num creates for NaN and +/- infinity.
        np.copyto(fdata, 0.0, where=np.isnan(fdata))
        image_u8 = fdata.astype(np.uint8)
    return RenderResult(
        image_u8=image_u8,
        width=width,
        height=height,
        invalid_pixels=data.invalid_pixels,
        resolved_spec=spec,
    )


def _robust_interval_limits(
    interval: Any,
    sample: np.ndarray,
    full_data: np.ndarray,
) -> tuple[float, float] | None:
    """Return finite limits, retrying interval estimation on finite values only."""

    try:
        vmin, vmax = interval.get_limits(sample)
    except Exception:
        vmin = vmax = np.nan
    if np.isfinite(vmin) and np.isfinite(vmax):
        return float(vmin), float(vmax)

    finite = sample[np.isfinite(sample)]
    if finite.size == 0 and sample is not full_data:
        finite = full_data[np.isfinite(full_data)]
    if finite.size == 0:
        return None

    try:
        vmin, vmax = interval.get_limits(finite)
    except Exception:
        vmin, vmax = np.min(finite), np.max(finite)
    if not (np.isfinite(vmin) and np.isfinite(vmax)):
        vmin, vmax = np.min(finite), np.max(finite)
    return float(vmin), float(vmax)


def compute_interval_limits(
    data: FITSData | None,
    interval_name: str,
    *,
    manual_limits: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    """Compute display ``(vmin, vmax)`` once so multiple render passes can reuse them.

    Used by render pipelines that want to apply the same brightness mapping
    across a preview stage and the eventual full-resolution render, avoiding
    redundant interval estimation (e.g. ZScale sigma-clipping) per stage.
    Returns ``None`` when there is no finite range; equal limits are a valid
    constant frame and must be shared unchanged by preview and full render.
    """

    if data is None or data.data is None:
        return None

    if manual_limits is not None:
        low, high = map(float, manual_limits)
        if not np.isfinite(low) or not np.isfinite(high):
            raise ValueError("Manual interval limits must be finite numbers.")
        if high <= low:
            raise ValueError("Manual interval high limit must be greater than low limit.")
        manual_limits = (low, high)
    interval = _build_interval(
        interval_name,
        manual_vmin=None if manual_limits is None else manual_limits[0],
        manual_vmax=None if manual_limits is None else manual_limits[1],
    )
    sample = data.data if interval_name == "Original" else _subsample(data.data)
    return _robust_interval_limits(interval, sample, data.data)


def _preview_dimensions(
    data: FITSData,
    max_dimension: int,
    max_output_pixels: int | None,
) -> tuple[int, int, int] | None:
    """Validate preview controls and return logical height, width and stride."""

    if data.data is None:
        return None
    if data.data.ndim != 2:
        raise ValueError("A preview requires a 2D image frame.")
    for name, value in (("max_dimension", max_dimension), ("max_output_pixels", max_output_pixels)):
        if value is None and name == "max_output_pixels":
            continue
        try:
            valid = not isinstance(value, bool) and operator.index(value) > 0
        except TypeError:
            valid = False
        if not valid:
            suffix = " or None" if name == "max_output_pixels" else ""
            raise ValueError(f"{name} must be a positive integer{suffix}.")
    height, width = data.data.shape
    longest_edge = max(height, width)
    if longest_edge <= max_dimension:
        return None
    step = max(2, (longest_edge + max_dimension - 1) // max_dimension)
    return height, width, step


def _check_preview_budget(output_pixels: int, max_output_pixels: int | None) -> None:
    if max_output_pixels is not None and output_pixels > max_output_pixels:
        raise ValueError(
            f"Preview output would contain {output_pixels:,} pixels, exceeding the "
            f"safety limit of {max_output_pixels:,}; pass a larger "
            "max_output_pixels value or None for trusted data."
        )


def render_preview_result(
    data: FITSData,
    stretch_name: str,
    interval_name: str,
    *,
    max_dimension: int = 2048,
    manual_limits: tuple[float, float] | None = None,
    max_output_pixels: int | None = DEFAULT_MAX_PREVIEW_OUTPUT_PIXELS,
    resolved_spec: ResolvedRenderSpec | None = None,
) -> RenderResult | None:
    """Render only sampled pixels, retaining the original coordinate extent.

    The pixel budget applies to the actual output texture. Input decoding
    budgets remain enforced by FITSData. Consumers must display this texture
    over ``width`` by ``height`` image coordinates, never use its array shape
    as the scientific image extent.
    """

    dimensions = _preview_dimensions(data, max_dimension, max_output_pixels)
    if dimensions is None:
        return None
    height, width, step = dimensions
    preview_data = data.data[::step, ::step]
    _check_preview_budget(int(preview_data.size), max_output_pixels)
    spec = resolved_spec or resolve_render_spec(
        data, stretch_name, interval_name, manual_limits=manual_limits
    )
    preview_image = render_image_u8(
        FITSData(data=preview_data),
        stretch_name,
        interval_name,
        resolved_spec=spec,
    )
    if preview_image is None:
        return None
    if preview_image.ndim != 2 or preview_image.shape != preview_data.shape:
        raise ValueError(
            "Preview renderer returned an unexpected shape: "
            f"expected {preview_data.shape}, got {preview_image.shape}."
        )
    return RenderResult(
        image_u8=preview_image,
        width=width,
        height=height,
        invalid_pixels=data.invalid_pixels,
        sample_step=step,
        resolved_spec=spec,
    )


def render_preview_u8(
    data: FITSData,
    stretch_name: str,
    interval_name: str,
    *,
    max_dimension: int = 2048,
    manual_limits: tuple[float, float] | None = None,
    max_output_pixels: int | None = DEFAULT_MAX_PREVIEW_OUTPUT_PIXELS,
    resolved_spec: ResolvedRenderSpec | None = None,
) -> np.ndarray | None:
    """Render a fast low-resolution preview and expand it back to image size.

    This compatibility API retains the original full-size array contract.
    New consumers can use render_preview_result and its logical dimensions.
    Expansion is performed one source row at a time
    to avoid the additional full-height temporary created by nested
    ``np.repeat`` calls.  ``max_output_pixels`` bounds the unavoidable final
    allocation; pass ``None`` only for trusted data.
    """

    dimensions = _preview_dimensions(data, max_dimension, max_output_pixels)
    if dimensions is None:
        return None
    height, width, step = dimensions
    _check_preview_budget(int(height) * int(width), max_output_pixels)
    result = render_preview_result(
        data,
        stretch_name,
        interval_name,
        max_dimension=max_dimension,
        manual_limits=manual_limits,
        max_output_pixels=max_output_pixels,
        resolved_spec=resolved_spec,
    )
    if result is None:
        return None
    preview_image = result.image_u8
    expanded = np.empty((height, width), dtype=preview_image.dtype)
    for source_y, row in enumerate(preview_image):
        start_y = source_y * step
        if start_y >= height:
            break
        end_y = min(height, start_y + step)
        expanded_row = np.repeat(row, step)[:width]
        expanded[start_y:end_y, :] = expanded_row
    return expanded


_PERCENTILE_INTERVALS: dict[str, float] = {
    "99.5%": 99.5,
    "99%": 99.0,
    "98%": 98.0,
    "95%": 95.0,
}


def _build_stretch(name: str) -> Any:
    viz = _astropy_visualization()
    stretch_map = {
        "Linear": viz["LinearStretch"],
        "Log": viz["LogStretch"],
        "Asinh": viz["AsinhStretch"],
        "Sqrt": viz["SqrtStretch"],
    }
    cls = stretch_map.get(name, viz["LinearStretch"])
    return cls()


def _build_interval(name: str, *, manual_vmin: float | None = None, manual_vmax: float | None = None) -> Any:
    viz = _astropy_visualization()
    if name == "ZScale":
        return viz["ZScaleInterval"]()
    if name == "MinMax":
        return viz["MinMaxInterval"]()
    if name == "Original":
        return _OriginalInterval()
    if name == "Manual":
        if manual_vmin is None or manual_vmax is None:
            return _OriginalInterval()
        return _ManualInterval(manual_vmin, manual_vmax)
    if name in _PERCENTILE_INTERVALS:
        return _PercentileInterval(_PERCENTILE_INTERVALS[name])
    return viz["ZScaleInterval"]()


class _PercentileInterval:
    """Simple percentile-based interval."""

    def __init__(self, percentile: float) -> None:
        self._lo = (100.0 - percentile) / 2.0
        self._hi = 100.0 - self._lo

    def get_limits(self, data: np.ndarray) -> tuple[float, float]:
        vmin, vmax = np.nanpercentile(data, [self._lo, self._hi])
        return float(vmin), float(vmax)


class _OriginalInterval:
    """Use the full image's real numeric range without percentile clipping."""

    def get_limits(self, data: np.ndarray) -> tuple[float, float]:
        vmin = np.nanmin(data)
        vmax = np.nanmax(data)
        return float(vmin), float(vmax)


class _ManualInterval:
    """Use explicit numeric display limits chosen by the user."""

    def __init__(self, vmin: float, vmax: float) -> None:
        self._vmin = float(vmin)
        self._vmax = float(vmax)

    def get_limits(self, data: np.ndarray) -> tuple[float, float]:
        return self._vmin, self._vmax


_SUBSAMPLE_MAX = 1000


def _subsample(data: np.ndarray, max_size: int = _SUBSAMPLE_MAX) -> np.ndarray:
    """Return a strided subsample for fast interval estimation."""

    h, w = data.shape[:2]
    if h <= max_size and w <= max_size:
        return data
    step_y = max(1, h // max_size)
    step_x = max(1, w // max_size)
    return data[::step_y, ::step_x]


def _finite_sample(data: np.ndarray, max_size: int = _SUBSAMPLE_MAX) -> np.ndarray:
    """Return a flattened finite-value sample suitable for histogram statistics."""

    sampled = _subsample(np.asarray(data), max_size=max_size)
    finite = sampled[np.isfinite(sampled)]
    return finite.reshape(-1)
