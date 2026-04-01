from __future__ import annotations

from typing import Any

import numpy as np
from astropy.visualization import (
    AsinhStretch,
    LinearStretch,
    LogStretch,
    ManualInterval,
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
    AVAILABLE_INTERVALS = ("ZScale", "MinMax", "99.5%", "99%", "98%", "95%")

    def __init__(self) -> None:
        self.current_data: FITSData | None = None
        self.current_stretch = self.AVAILABLE_STRETCHES[0]
        self.current_interval = self.AVAILABLE_INTERVALS[0]

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

    def build_render_request(self) -> RenderRequest:
        """Build a render request from the current service configuration."""

        return RenderRequest(
            stretch_name=self.current_stretch,
            interval_name=self.current_interval,
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

        interval = _build_interval(request.interval_name)
        stretch = _build_stretch(request.stretch_name)

        vmin, vmax = interval.get_limits(data)
        clipped = np.clip(data, vmin, vmax)
        if vmax > vmin:
            normalized = (clipped - vmin) / (vmax - vmin)
        else:
            normalized = np.zeros_like(clipped)

        stretched = stretch(normalized)
        image_u8 = (stretched * 255).astype(np.uint8)

        return RenderResult(image_u8=image_u8, width=w, height=h)

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


def _build_interval(name: str) -> Any:
    if name == "ZScale":
        return ZScaleInterval()
    if name == "MinMax":
        return MinMaxInterval()
    if name in _PERCENTILE_INTERVALS:
        pct = _PERCENTILE_INTERVALS[name]
        lo = (100.0 - pct) / 2.0
        hi = 100.0 - lo
        return ManualInterval(*np.percentile([], [lo, hi])) if False else _PercentileInterval(pct)
    return ZScaleInterval()


class _PercentileInterval:
    """Simple percentile-based interval."""

    def __init__(self, percentile: float) -> None:
        self._lo = (100.0 - percentile) / 2.0
        self._hi = 100.0 - self._lo

    def get_limits(self, data: np.ndarray) -> tuple[float, float]:
        vmin, vmax = np.nanpercentile(data, [self._lo, self._hi])
        return float(vmin), float(vmax)
