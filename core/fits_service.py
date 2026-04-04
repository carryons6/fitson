from __future__ import annotations

from typing import Any

import numpy as np
from astropy.visualization import (
    AsinhStretch,
    LinearStretch,
    LogStretch,
    MinMaxInterval,
    SqrtStretch,
    ZScaleInterval,
)

from .contracts import RenderRequest, RenderResult
from .fits_data import FITSData, HDUInfo


class FITSService:
    """FITS loading and rendering service skeleton.

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
        from astropy.io import fits as astro_fits

        with astro_fits.open(path, memmap=True) as hdul:
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

    def render(self, request: RenderRequest | None = None) -> RenderResult:
        """Render the active FITS dataset to a display-oriented 8-bit result.

        Expected flow:
        `MainWindow.refresh_image()` -> `FITSService.render()` -> `ImageCanvas.set_image()`.
        """

        request = request or self.build_render_request()

        if self.current_data is None or self.current_data.data is None:
            return RenderResult(image_u8=None)

        data = self.current_data.data
        h, w = data.shape[:2]

        interval = _build_interval(
            request.interval_name,
            manual_vmin=request.manual_vmin,
            manual_vmax=request.manual_vmax,
        )
        stretch = _build_stretch(request.stretch_name)

        # Keep "Original" on the full image; other interval modes can subsample large data.
        sample = data if request.interval_name == "Original" else _subsample(data)
        vmin, vmax = interval.get_limits(sample)

        # In-place pipeline to minimize allocations
        fdata = data.astype(np.float32, copy=True)
        np.clip(fdata, vmin, vmax, out=fdata)
        if vmax > vmin:
            fdata -= vmin
            fdata /= (vmax - vmin)
        else:
            fdata[:] = 0

        stretched = stretch(fdata)
        if stretched is not fdata:
            fdata = stretched
        np.multiply(fdata, 255, out=fdata)
        image_u8 = fdata.astype(np.uint8)

        return RenderResult(image_u8=image_u8, width=w, height=h)

    def finite_data_range(self, data: FITSData | None = None) -> tuple[float, float] | None:
        """Return the finite numeric range of the current image data."""

        target = self.current_data if data is None else data
        if target is None or target.data is None:
            return None

        finite = _finite_sample(target.data)
        if finite.size == 0:
            return None

        return float(np.nanmin(finite)), float(np.nanmax(finite))

    def histogram(self, data: FITSData | None = None, *, bins: int = 256) -> tuple[np.ndarray, float, float]:
        """Return histogram counts and numeric range for the current image."""

        target = self.current_data if data is None else data
        if target is None or target.data is None:
            return np.zeros(bins, dtype=np.int64), 0.0, 0.0

        finite = _finite_sample(target.data)
        if finite.size == 0:
            return np.zeros(bins, dtype=np.int64), 0.0, 0.0

        min_value = float(np.nanmin(finite))
        max_value = float(np.nanmax(finite))
        if max_value <= min_value:
            counts = np.zeros(bins, dtype=np.int64)
            counts[0] = int(finite.size)
            return counts, min_value, max_value

        counts, _edges = np.histogram(finite, bins=bins, range=(min_value, max_value))
        return counts.astype(np.int64, copy=False), min_value, max_value

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
) -> np.ndarray | None:
    """Render a FITSData object to an 8-bit grayscale numpy image."""

    service = FITSService()
    service.current_data = data
    service.set_stretch(stretch_name)
    service.set_interval(interval_name)
    if manual_limits is not None:
        service.set_manual_interval_limits(*manual_limits)
    return service.render().image_u8


def render_preview_u8(
    data: FITSData,
    stretch_name: str,
    interval_name: str,
    *,
    max_dimension: int = 2048,
    manual_limits: tuple[float, float] | None = None,
) -> np.ndarray | None:
    """Render a fast low-resolution preview and expand it back to image size."""

    if data.data is None:
        return None

    height, width = data.data.shape[:2]
    longest_edge = max(height, width)
    if longest_edge <= max_dimension:
        return None

    step = max(2, (longest_edge + max_dimension - 1) // max_dimension)
    preview_data = data.data[::step, ::step]
    preview_image = render_image_u8(
        FITSData(data=preview_data),
        stretch_name,
        interval_name,
        manual_limits=manual_limits,
    )
    if preview_image is None:
        return None

    preview_image = np.repeat(np.repeat(preview_image, step, axis=0), step, axis=1)
    return preview_image[:height, :width]


_STRETCH_MAP: dict[str, type] = {
    "Linear": LinearStretch,
    "Log": LogStretch,
    "Asinh": AsinhStretch,
    "Sqrt": SqrtStretch,
}

_PERCENTILE_INTERVALS: dict[str, float] = {
    "99.5%": 99.5,
    "99%": 99.0,
    "98%": 98.0,
    "95%": 95.0,
}


def _build_stretch(name: str) -> Any:
    cls = _STRETCH_MAP.get(name, LinearStretch)
    return cls()


def _build_interval(name: str, *, manual_vmin: float | None = None, manual_vmax: float | None = None) -> Any:
    if name == "ZScale":
        return ZScaleInterval()
    if name == "MinMax":
        return MinMaxInterval()
    if name == "Original":
        return _OriginalInterval()
    if name == "Manual":
        if manual_vmin is None or manual_vmax is None:
            return _OriginalInterval()
        return _ManualInterval(manual_vmin, manual_vmax)
    if name in _PERCENTILE_INTERVALS:
        pct = _PERCENTILE_INTERVALS[name]
        lo = (100.0 - pct) / 2.0
        hi = 100.0 - lo
        return _PercentileInterval(pct)
    return ZScaleInterval()


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
