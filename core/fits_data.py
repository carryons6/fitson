from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import warnings

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.wcs import FITSFixedWarning

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
        data = _read_hdu_data(path, idx, hdul)

        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', FITSFixedWarning)
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
        if not _is_image_hdu(hdu):
            continue
        dimensions = _hdu_dimensions(hdu)
        if len(dimensions) < 2:
            continue
        result.append(HDUInfo(
            index=i,
            name=hdu.name or f"HDU {i}",
            dimensions=dimensions,
            dtype_name=_dtype_name_from_header(hdu.header),
        ))
    return result


def _read_hdu_data(path: str, hdu_index: int, hdul: fits.HDUList) -> np.ndarray | None:
    """Read one image HDU, retrying without memmap for scaled integer FITS data."""

    try:
        data = hdul[hdu_index].data
    except ValueError as exc:
        if not _should_retry_without_memmap(exc, hdul[hdu_index].header):
            raise
        with fits.open(path, memmap=False) as fallback_hdul:
            data = fallback_hdul[hdu_index].data

    if data is None:
        return None

    array = np.asarray(data)
    if not array.dtype.isnative:
        array = array.astype(array.dtype.newbyteorder("="))
    return array


def _should_retry_without_memmap(exc: ValueError, header: Any) -> bool:
    """Detect the astropy memmap limitation for scaled FITS image data."""

    message = str(exc).lower()
    has_scaling = any(key in header for key in ("BSCALE", "BZERO", "BLANK"))
    return "memmap" in message or has_scaling


def _is_image_hdu(hdu: Any) -> bool:
    """Return whether an HDU can expose image-like pixel data."""

    comp_image_hdu = getattr(fits, "CompImageHDU", ())
    return isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU, comp_image_hdu))


def _hdu_dimensions(hdu: Any) -> tuple[int, ...]:
    """Return image dimensions from header metadata without touching pixel data."""

    shape = getattr(hdu, "shape", None)
    if shape is not None:
        return tuple(int(size) for size in shape)

    header = getattr(hdu, "header", None)
    if header is None:
        return ()

    axis_count = int(header.get("NAXIS", 0) or 0)
    if axis_count <= 0:
        return ()

    dimensions: list[int] = []
    for axis in range(axis_count, 0, -1):
        size = header.get(f"NAXIS{axis}")
        if size is None:
            return ()
        dimensions.append(int(size))
    return tuple(dimensions)


def _dtype_name_from_header(header: Any) -> str:
    """Summarize the pixel type from FITS header cards."""

    try:
        bitpix = int(header.get("BITPIX"))
    except Exception:
        return ""

    dtype_name = {
        8: "uint8",
        16: "int16",
        32: "int32",
        64: "int64",
        -32: "float32",
        -64: "float64",
    }.get(bitpix, f"BITPIX={bitpix}")

    bzero = header.get("BZERO")
    bscale = header.get("BSCALE", 1)
    if bitpix == 16 and bzero == 32768 and bscale == 1:
        return "uint16"
    return dtype_name
