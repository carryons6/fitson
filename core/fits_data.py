from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from .contracts import PixelSample


@dataclass(slots=True)
class HDUInfo:
    """Metadata for a selectable image HDU."""

    index: int
    name: str
    dimensions: tuple[int, ...] = ()
    dtype_name: str = ""


@dataclass(slots=True)
class FITSData:
    """Container for the current FITS image, header, and WCS state.

    Ownership contract:
    - Created and updated by `FITSService`.
    - Read by `MainWindow` for cursor sampling and ROI slicing.
    - Never manipulated directly by view classes.
    """

    path: str | None = None
    hdu_index: int | None = None
    data: np.ndarray | None = None
    header: Any = None
    wcs: Any = None
    has_wcs: bool = False
    invalid_pixels: bool = False
    available_hdus: list[HDUInfo] = field(default_factory=list)

    @classmethod
    def load(cls, path: str, hdu_index: int | None = None) -> "FITSData":
        """Load FITS data from disk into the container.

        Called by `FITSService.open_file()`.
        Uses memmap=True for large files.
        """

        hdul = fits.open(path, memmap=True)
        available = _scan_image_hdus(hdul)

        if hdu_index is not None:
            idx = hdu_index
        elif available:
            idx = available[0].index
        else:
            hdul.close()
            return cls(path=path, available_hdus=available)

        hdu = hdul[idx]
        header = hdu.header
        data = hdu.data
        if data is not None:
            data = np.asarray(data, dtype=np.float32)

        try:
            wcs = WCS(header)
            has_wcs = wcs.has_celestial
        except Exception:
            wcs = None
            has_wcs = False

        return cls(
            path=path,
            hdu_index=idx,
            data=data,
            header=header,
            wcs=wcs,
            has_wcs=has_wcs,
            available_hdus=available,
        )

    def get_data(self) -> np.ndarray | None:
        """Return the current image array."""

        return self.data

    def get_header(self) -> Any:
        """Return the current FITS header object."""

        return self.header

    def header_as_text(self) -> str:
        """Return the full FITS header rendered as plain text."""

        if self.header is None:
            return ""
        return self.header.tostring(sep="\n")

    def get_wcs(self) -> Any:
        """Return the current WCS object."""

        return self.wcs

    def pixel_to_world(self, x: float, y: float) -> tuple[float, float] | None:
        """Convert a pixel coordinate to world coordinates (ra, dec in degrees).

        Called by `MainWindow.update_status_from_cursor()`.
        """

        if not self.has_wcs or self.wcs is None:
            return None
        try:
            result = self.wcs.pixel_to_world(x, y)
            return (result.ra.deg, result.dec.deg)
        except Exception:
            return None

    def sample_pixel(self, x: int, y: int) -> PixelSample:
        """Return a status-bar oriented sample for one image pixel.

        Intended call chain:
        `ImageCanvas.mouse_moved` -> `MainWindow.update_status_from_cursor`
        -> `FITSData.sample_pixel` -> `AppStatusBar.set_sample`.
        """

        if self.data is None:
            return PixelSample(x=x, y=y)

        h, w = self.data.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return PixelSample(x=x, y=y, inside_image=False)

        value = float(self.data[y, x])
        world = self.pixel_to_world(float(x), float(y))
        ra_str = f"{world[0]:.6f}" if world else None
        dec_str = f"{world[1]:.6f}" if world else None

        return PixelSample(
            x=x, y=y, value=value,
            ra=ra_str, dec=dec_str,
            inside_image=True,
        )


def _scan_image_hdus(hdul: fits.HDUList) -> list[HDUInfo]:
    """Scan an HDU list and return metadata for HDUs that contain image data."""

    result: list[HDUInfo] = []
    for i, hdu in enumerate(hdul):
        if not isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU)):
            continue
        if hdu.data is None:
            continue
        if hdu.data.ndim < 2:
            continue
        result.append(HDUInfo(
            index=i,
            name=hdu.name or f"HDU {i}",
            dimensions=tuple(hdu.data.shape),
            dtype_name=str(hdu.data.dtype),
        ))
    return result
