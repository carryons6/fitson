from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import mmap
import operator
import os
from pathlib import Path
import stat
from typing import Any
import warnings

import numpy as np

from .contracts import PixelSample


# Loading a FITS image can allocate much more memory than the compressed/on-disk
# file size suggests.  These defaults admit a normal 8k x 8k image (including
# float64 data) while rejecting pathological headers and cubes before Astropy
# materializes ``hdu.data``.  Pass ``None`` for an individual limit to disable
# it, or a larger integer for trusted data sets.
DEFAULT_MAX_PIXELS = 8_192**2
DEFAULT_MAX_DECODED_BYTES = 512 * 1024**2
DEFAULT_MAX_FRAMES = 4_096

_OUTER_COMPRESSION_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x1f\x8b", "gzip"),
    (b"\x1f\x9d", "Unix compress/LZW"),
    (b"BZh", "bzip2"),
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP"),
    (b"PK\x07\x08", "ZIP"),
    (b"\xfd7zXZ\x00", "xz/LZMA"),
    (b"]\x00\x00\x80\x00", "LZMA"),
)


def _astropy_fits():
    """Import `astropy.io.fits` lazily to keep module import cheap at startup."""

    from astropy.io import fits

    return fits


def _astropy_wcs_types():
    """Return ``(WCS, FITSFixedWarning)`` via a single deferred import."""

    from astropy.wcs import WCS
    from astropy.wcs.wcs import FITSFixedWarning

    return WCS, FITSFixedWarning


def __getattr__(name: str):
    """Expose lazily-imported astropy attributes for ``patch()`` / introspection.

    Without this, attribute access like ``core.fits_data.fits`` or
    ``core.fits_data.WCS`` would fail because those names are no longer bound
    at module level. Importing on demand keeps the startup cost deferred.
    """

    if name == "fits":
        fits = _astropy_fits()
        globals()["fits"] = fits
        return fits
    if name in ("WCS", "FITSFixedWarning"):
        WCS, FITSFixedWarning = _astropy_wcs_types()
        globals()["WCS"] = WCS
        globals()["FITSFixedWarning"] = FITSFixedWarning
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    frame_index: int = 0
    frame_count: int = 1
    frame_coordinates: tuple[int, ...] = ()
    source_group_id: int | None = None

    @classmethod
    def load(
        cls,
        path: str,
        hdu_index: int | None = None,
        *,
        max_pixels: int | None = DEFAULT_MAX_PIXELS,
        max_decoded_bytes: int | None = DEFAULT_MAX_DECODED_BYTES,
        max_frames: int | None = DEFAULT_MAX_FRAMES,
    ) -> "FITSData":
        """Load FITS data from disk into the container.

        Called by `FITSService.open_file()`.
        Uses memmap=True for large files.
        """
        return cls.load_frames(
            path,
            hdu_index,
            max_pixels=max_pixels,
            max_decoded_bytes=max_decoded_bytes,
            max_frames=max_frames,
        )[0]

    @classmethod
    def load_frames(
        cls,
        path: str,
        hdu_index: int | None = None,
        *,
        source_group_id: int | None = None,
        max_pixels: int | None = DEFAULT_MAX_PIXELS,
        max_decoded_bytes: int | None = DEFAULT_MAX_DECODED_BYTES,
        max_frames: int | None = DEFAULT_MAX_FRAMES,
    ) -> list["FITSData"]:
        """Load one FITS HDU and expand multidimensional image data into 2D frames.

        Resource limits are checked from HDU metadata before pixel data is
        decoded.  Set a limit to ``None`` to disable that check for trusted
        files.
        """

        loaded_hdu = _load_hdu_data(
            path,
            hdu_index,
            max_pixels=max_pixels,
            max_decoded_bytes=max_decoded_bytes,
            max_frames=max_frames,
        )
        return _expand_loaded_hdu_to_frames(loaded_hdu, source_group_id=source_group_id)

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

    def save_to(self, path: str, *, overwrite: bool = False) -> None:
        """Write the current frame's raw data and header to a FITS file.

        The original header is passed through so WCS, units, and other
        provenance keywords are preserved; astropy will update NAXIS/BITPIX
        to match ``self.data`` automatically.
        """

        if self.data is None:
            raise ValueError("No image data available to save.")
        fits = _astropy_fits()
        hdu = fits.PrimaryHDU(data=np.asarray(self.data), header=self.header)
        hdu.writeto(path, overwrite=overwrite)

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


def _scan_image_hdus(hdul: Any) -> list[HDUInfo]:
    """Scan an HDU list and return metadata for HDUs that contain image data."""

    result: list[HDUInfo] = []
    for i, hdu in enumerate(hdul):
        if not _is_image_hdu(hdu):
            continue
        dimensions = _hdu_dimensions(hdu)
        if len(dimensions) < 2 or any(size <= 0 for size in dimensions):
            continue
        result.append(HDUInfo(
            index=i,
            name=hdu.name or f"HDU {i}",
            dimensions=dimensions,
            dtype_name=_dtype_name_from_header(hdu.header),
        ))
    return result


@dataclass(slots=True)
class _LoadedHDUData:
    """Resolved HDU payload before it is expanded into 2D frame objects."""

    path: str
    hdu_index: int | None = None
    data: np.ndarray | None = None
    header: Any = None
    wcs: Any = None
    has_wcs: bool = False
    available_hdus: list[HDUInfo] = field(default_factory=list)


class _RetryWithoutMemmap:
    """Sentinel requesting that the stable FITS source be reopened without memmap."""


def _normalize_limit(name: str, value: int | None) -> int | None:
    """Validate one public resource-limit argument."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer or None.")
    try:
        normalized = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a positive integer or None.") from exc
    if normalized <= 0:
        raise ValueError(f"{name} must be a positive integer or None.")
    return normalized


def _validate_input_container(stream: Any, path: str) -> None:
    """Validate one already-open input handle before Astropy consumes it.

    AstroView supports ordinary FITS files and FITS tile compression through
    ``CompImageHDU``.  Transparent outer compression has no trustworthy decoded
    size available before Astropy expands it, so accepting it would bypass the
    image allocation budget even when a compressed stream is disguised with a
    ``.fits`` suffix.
    """

    try:
        source_stat = os.fstat(stream.fileno())
    except (AttributeError, OSError, ValueError) as exc:
        raise ValueError(f"Could not inspect FITS input {path!r}: {exc}") from exc

    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError(f"FITS input must be a regular local file: {path!r}.")

    try:
        prefix = stream.read(8)
        stream.seek(0)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not inspect FITS input {path!r}: {exc}") from exc

    for signature, label in _OUTER_COMPRESSION_SIGNATURES:
        if prefix.startswith(signature):
            raise ValueError(
                f"Whole-file {label} compression is not supported safely. "
                "Decompress the file after verifying its expanded size, or use "
                "FITS tile compression (CompImageHDU)."
            )


@contextmanager
def _open_validated_fits_source(path: str) -> Iterator[Any]:
    """Open and validate one stable, unbuffered master handle."""

    source = Path(path)
    try:
        stream = source.open("rb", buffering=0)
    except FileNotFoundError:
        raise
    except OSError as exc:
        try:
            is_non_regular = source.exists() and not source.is_file()
        except OSError:
            is_non_regular = False
        if is_non_regular:
            raise ValueError(f"FITS input must be a regular local file: {path!r}.") from exc
        raise ValueError(f"Could not inspect FITS input {path!r}: {exc}") from exc

    with stream:
        _validate_input_container(stream, path)
        yield stream


@contextmanager
def _open_fits_from_source(stream: Any, *, memmap: bool) -> Iterator[Any]:
    """Open Astropy on a duplicate of an already-validated stable handle."""

    stream.seek(0)
    duplicate_fd = os.dup(stream.fileno())
    try:
        duplicate = os.fdopen(duplicate_fd, "rb", buffering=0)
    except Exception:
        os.close(duplicate_fd)
        raise

    try:
        hdul = _astropy_fits().open(duplicate, memmap=memmap)
    except Exception:
        duplicate.close()
        raise
    try:
        yield hdul
    finally:
        try:
            hdul.close()
        finally:
            duplicate.close()


@contextmanager
def open_fits_container(path: str, *, memmap: bool = True) -> Iterator[Any]:
    """Open a FITS container only after applying the shared safety checks.

    All path-based FITS inspection must use this entry point so Astropy cannot
    transparently expand a whole-file compressed stream that merely carries a
    normal FITS suffix.  FITS tile compression remains supported because its
    outer container is an ordinary FITS file.
    """

    with _open_validated_fits_source(path) as stream:
        with _open_fits_from_source(stream, memmap=memmap) as hdul:
            yield hdul


def _normalize_hdu_index(hdu_index: int, hdu_count: int) -> int:
    """Return a non-negative, in-range HDU index with a readable error."""

    if isinstance(hdu_index, bool):
        raise ValueError("HDU index must be a non-negative integer.")
    try:
        idx = operator.index(hdu_index)
    except TypeError as exc:
        raise ValueError("HDU index must be a non-negative integer.") from exc
    if idx < 0 or idx >= hdu_count:
        if hdu_count:
            expected = f"0 through {hdu_count - 1}"
        else:
            expected = "no HDUs are present"
        raise ValueError(f"HDU index {idx} is out of range ({expected}).")
    return idx


def _validate_image_hdu(hdu: Any, hdu_index: int) -> tuple[int, ...]:
    """Validate HDU kind and shape without accessing its pixel payload."""

    if not _is_image_hdu(hdu):
        kind = type(hdu).__name__
        raise ValueError(
            f"HDU {hdu_index} is a {kind}, not an image HDU; select a non-empty "
            "PrimaryHDU, ImageHDU, or CompImageHDU with at least two dimensions."
        )

    try:
        dimensions = _hdu_dimensions(hdu)
    except Exception as exc:
        raise ValueError(f"HDU {hdu_index} has invalid image dimensions: {exc}") from exc
    if not dimensions:
        raise ValueError(f"HDU {hdu_index} is empty and contains no image pixels.")
    if len(dimensions) < 2:
        raise ValueError(
            f"HDU {hdu_index} is one-dimensional with shape {dimensions}; "
            "at least a 2D image is required."
        )
    if any(size <= 0 for size in dimensions):
        raise ValueError(f"HDU {hdu_index} is an empty image with shape {dimensions}.")
    return dimensions


def _dimension_product(dimensions: tuple[int, ...]) -> int:
    """Multiply dimensions using unbounded Python integers."""

    result = 1
    for size in dimensions:
        result *= size
    return result


def _decoded_bytes_per_pixel(header: Any) -> int:
    """Conservatively estimate Astropy's decoded element size from a header."""

    try:
        bitpix = abs(int(header.get("BITPIX")))
        element_bytes = max(1, (bitpix + 7) // 8)
    except Exception:
        # A malformed/missing BITPIX should not bypass the allocation guard.
        element_bytes = 8

    # Scaling or BLANK replacement can promote integer data to floating point.
    # Eight bytes is a conservative bound for Astropy's standard image types.
    try:
        has_scaling = (
            header.get("BSCALE", 1) != 1
            or header.get("BZERO", 0) != 0
            or "BLANK" in header
        )
    except Exception:
        has_scaling = True
    if has_scaling:
        element_bytes = max(element_bytes, 8)
    return element_bytes


def _enforce_load_limits(
    dimensions: tuple[int, ...],
    header: Any,
    *,
    hdu_index: int,
    max_pixels: int | None,
    max_decoded_bytes: int | None,
    max_frames: int | None,
) -> None:
    """Reject unsafe image metadata before ``hdu.data`` is evaluated."""

    pixel_count = _dimension_product(dimensions)
    frame_count = _dimension_product(dimensions[:-2]) if len(dimensions) > 2 else 1
    decoded_bytes = pixel_count * _decoded_bytes_per_pixel(header)

    if max_pixels is not None and pixel_count > max_pixels:
        raise ValueError(
            f"HDU {hdu_index} declares {pixel_count:,} pixels, exceeding the safety "
            f"limit of {max_pixels:,}; pass a larger max_pixels value or None for trusted files."
        )
    if max_decoded_bytes is not None and decoded_bytes > max_decoded_bytes:
        raise ValueError(
            f"HDU {hdu_index} may require about {decoded_bytes:,} decoded bytes, exceeding "
            f"the safety limit of {max_decoded_bytes:,}; pass a larger "
            "max_decoded_bytes value or None for trusted files."
        )
    if max_frames is not None and frame_count > max_frames:
        raise ValueError(
            f"HDU {hdu_index} would expand into {frame_count:,} frames, exceeding the "
            f"safety limit of {max_frames:,}; pass a larger max_frames value or None "
            "for trusted files."
        )


def _validate_decoded_array(data: Any, hdu_index: int) -> None:
    """Defend against decoded payloads that disagree with valid image metadata."""

    array = np.asarray(data)
    if array.ndim < 2:
        raise ValueError(
            f"HDU {hdu_index} decoded as {array.ndim}D data; at least a 2D image is required."
        )
    if any(size <= 0 for size in array.shape):
        raise ValueError(f"HDU {hdu_index} decoded as an empty image with shape {array.shape}.")


def _load_hdu_data(
    path: str,
    hdu_index: int | None = None,
    *,
    max_pixels: int | None = DEFAULT_MAX_PIXELS,
    max_decoded_bytes: int | None = DEFAULT_MAX_DECODED_BYTES,
    max_frames: int | None = DEFAULT_MAX_FRAMES,
) -> _LoadedHDUData:
    """Load one HDU from disk and return the raw image payload plus metadata."""

    limits = (
        _normalize_limit("max_pixels", max_pixels),
        _normalize_limit("max_decoded_bytes", max_decoded_bytes),
        _normalize_limit("max_frames", max_frames),
    )
    with _open_validated_fits_source(path) as stream:
        with _open_fits_from_source(stream, memmap=True) as hdul:
            loaded = _load_hdu_from_open_list(
                path,
                hdu_index,
                hdul,
                limits,
                allow_memmap_retry=True,
            )
        del hdul

        if isinstance(loaded, _RetryWithoutMemmap):
            with _open_fits_from_source(stream, memmap=False) as fallback_hdul:
                loaded = _load_hdu_from_open_list(
                    path,
                    hdu_index,
                    fallback_hdul,
                    limits,
                    allow_memmap_retry=False,
                )
            del fallback_hdul

        if isinstance(loaded, _RetryWithoutMemmap):
            raise RuntimeError("Unexpected repeated memmap fallback request.")
        return loaded


def _load_hdu_from_open_list(
    path: str,
    hdu_index: int | None,
    hdul: Any,
    limits: tuple[int | None, int | None, int | None],
    *,
    allow_memmap_retry: bool,
) -> _LoadedHDUData | _RetryWithoutMemmap:
    """Validate and load one HDU from a concrete Astropy HDUList."""

    available = _scan_image_hdus(hdul)

    if hdu_index is not None:
        idx = _normalize_hdu_index(hdu_index, len(hdul))
    elif available:
        idx = available[0].index
    else:
        raise ValueError(
            "No non-empty image HDU with at least two dimensions was found "
            f"in {path!r}."
        )

    hdu = hdul[idx]
    dimensions = _validate_image_hdu(hdu, idx)
    _enforce_load_limits(
        dimensions,
        hdu.header,
        hdu_index=idx,
        max_pixels=limits[0],
        max_decoded_bytes=limits[1],
        max_frames=limits[2],
    )

    try:
        data = _read_hdu_data(path, idx, hdul)
    except ValueError as exc:
        if allow_memmap_retry and _should_retry_without_memmap(exc, hdu.header):
            return _RetryWithoutMemmap()
        raise
    if data is None:
        raise ValueError(f"HDU {idx} declares image dimensions but contains no readable pixel data.")
    _validate_decoded_array(data, idx)

    header = hdu.header.copy()
    wcs, has_wcs = _build_frame_wcs(header)
    return _LoadedHDUData(
        path=path,
        hdu_index=idx,
        data=data,
        header=header,
        wcs=wcs,
        has_wcs=has_wcs,
        available_hdus=available,
    )


def _expand_loaded_hdu_to_frames(
    loaded_hdu: _LoadedHDUData,
    *,
    source_group_id: int | None = None,
) -> list[FITSData]:
    """Expand one loaded HDU into one or more 2D FITSData frame objects."""

    if loaded_hdu.data is None:
        raise ValueError("The selected HDU contains no image data.")

    array = np.asarray(loaded_hdu.data)
    if array.ndim < 2:
        raise ValueError(f"The selected HDU is {array.ndim}D; at least a 2D image is required.")
    if any(size <= 0 for size in array.shape):
        raise ValueError(f"The selected HDU is an empty image with shape {array.shape}.")
    if array.ndim == 2:
        return [_build_frame(loaded_hdu, data=array, source_group_id=source_group_id)]

    frame_axes = tuple(int(size) for size in array.shape[:-2])
    frame_count = _dimension_product(frame_axes)
    frames: list[FITSData] = []
    for frame_index, frame_coordinates in enumerate(np.ndindex(*frame_axes)):
        frames.append(_build_frame(
            loaded_hdu,
            data=array[frame_coordinates],
            frame_index=frame_index,
            frame_count=frame_count,
            frame_coordinates=tuple(int(value) for value in frame_coordinates),
            source_group_id=source_group_id,
        ))
    return frames


def _build_frame(
    loaded_hdu: _LoadedHDUData,
    *,
    data: np.ndarray | None = None,
    frame_index: int = 0,
    frame_count: int = 1,
    frame_coordinates: tuple[int, ...] = (),
    source_group_id: int | None = None,
) -> FITSData:
    """Build one FITSData frame instance from loaded HDU metadata."""

    return FITSData(
        path=loaded_hdu.path,
        hdu_index=loaded_hdu.hdu_index,
        data=data if data is not None else loaded_hdu.data,
        header=loaded_hdu.header,
        wcs=loaded_hdu.wcs,
        has_wcs=loaded_hdu.has_wcs,
        available_hdus=loaded_hdu.available_hdus,
        frame_index=frame_index,
        frame_count=frame_count,
        frame_coordinates=frame_coordinates,
        source_group_id=source_group_id,
    )


def _read_hdu_data(path: str, hdu_index: int, hdul: Any) -> np.ndarray | None:
    """Read one image HDU into native, process-owned memory.

    Astropy's memmap is useful while decoding, but returning an array backed by
    that mapping keeps the source file locked on Windows.  Detaching here makes
    close/overwrite semantics deterministic and keeps the allocation covered by
    the metadata budget enforced before this function is called.
    """

    data = hdul[hdu_index].data

    if data is None:
        return None

    array = np.asarray(data)
    needs_detach = _array_uses_memory_map(array) or not array.flags.c_contiguous
    if not array.dtype.isnative:
        native_dtype = array.dtype.newbyteorder("=")
        return np.array(array, dtype=native_dtype, order="C", copy=True)
    if needs_detach:
        return np.array(array, order="C", copy=True)
    return array


def _array_uses_memory_map(array: np.ndarray) -> bool:
    """Return whether an ndarray's ownership chain reaches a live mmap."""

    owner: Any = array
    seen: set[int] = set()
    while owner is not None and id(owner) not in seen:
        seen.add(id(owner))
        if isinstance(owner, (np.memmap, mmap.mmap)):
            return True
        owner = getattr(owner, "base", None)
    return False


def _should_retry_without_memmap(exc: ValueError, header: Any) -> bool:
    """Detect the astropy memmap limitation for scaled FITS image data."""

    message = str(exc).lower()
    has_scaling = any(key in header for key in ("BSCALE", "BZERO", "BLANK"))
    return "memmap" in message or has_scaling


def _build_frame_wcs(header: Any) -> tuple[Any, bool]:
    """Build a WCS object suitable for per-frame 2D interaction."""

    try:
        WCS, FITSFixedWarning = _astropy_wcs_types()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FITSFixedWarning)
            full_wcs = WCS(header)
        if full_wcs.has_celestial:
            try:
                return full_wcs.celestial, True
            except Exception:
                return full_wcs, True
        return full_wcs, False
    except Exception:
        return None, False


def _is_image_hdu(hdu: Any) -> bool:
    """Return whether an HDU can expose image-like pixel data."""

    fits = _astropy_fits()
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
