from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import operator
from typing import Any

import numpy as np

from .fits_data import DEFAULT_MAX_DECODED_BYTES, DEFAULT_MAX_PIXELS, FITSData


DEFAULT_MAX_COMPARISON_PIXELS = DEFAULT_MAX_PIXELS
DEFAULT_MAX_WCS_REPROJECT_PIXELS = 4_096**2
DEFAULT_MAX_COMPARISON_BYTES = DEFAULT_MAX_DECODED_BYTES
DEFAULT_COMPARISON_CHUNK_ROWS = 256
DEFAULT_WCS_ROUNDTRIP_TOLERANCE = 0.25


class ComparisonMode(str, Enum):
    """Presentation mode requested by the comparison UI."""

    SIDE_BY_SIDE = "side_by_side"
    BLINK = "blink"
    DIFFERENCE = "difference"


class ComparisonAlignment(str, Enum):
    """How the right image should be placed on the left image grid."""

    AUTO = "auto"
    PIXEL = "pixel"
    WCS = "wcs"


class ComparisonFailureCode(str, Enum):
    """Stable machine-readable reasons for a rejected comparison request."""

    INVALID_OPTION = "invalid_option"
    MISSING_DATA = "missing_data"
    INVALID_DIMENSIONS = "invalid_dimensions"
    UNSUPPORTED_DTYPE = "unsupported_dtype"
    SHAPE_MISMATCH = "shape_mismatch"
    OUTPUT_LIMIT = "output_limit"
    MEMORY_LIMIT = "memory_limit"
    MISSING_WCS = "missing_wcs"
    UNSUPPORTED_WCS = "unsupported_wcs"
    WCS_TRANSFORM_FAILED = "wcs_transform_failed"
    WCS_UNRELIABLE = "wcs_unreliable"
    NO_OVERLAP = "no_overlap"


@dataclass(slots=True)
class ImageComparisonResult:
    """Bounded, display-oriented output from :func:`compare_fits_images`.

    ``left_image`` and ``right_image`` are populated for side-by-side and blink
    modes.  ``difference_image`` is populated for difference mode and is always
    ``left - right`` on the left image's pixel grid.  WCS resampling uses a
    deliberately limited nearest-neighbour path; pixels outside the overlap or
    containing NaN/Inf are represented by NaN.
    """

    success: bool
    mode: ComparisonMode | None
    alignment_used: ComparisonAlignment | None = None
    left_image: np.ndarray | None = None
    right_image: np.ndarray | None = None
    difference_image: np.ndarray | None = None
    output_shape: tuple[int, int] | None = None
    finite_overlap_pixels: int = 0
    invalid_overlap_pixels: int = 0
    reason_code: ComparisonFailureCode | None = None
    reason: str | None = None
    warning: str | None = None

    @classmethod
    def failure(
        cls,
        code: ComparisonFailureCode,
        reason: str,
        *,
        mode: ComparisonMode | None = None,
        output_shape: tuple[int, int] | None = None,
    ) -> "ImageComparisonResult":
        return cls(
            success=False,
            mode=mode,
            output_shape=output_shape,
            reason_code=code,
            reason=reason,
        )


class _ComparisonRejected(ValueError):
    def __init__(self, code: ComparisonFailureCode, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def compare_fits_images(
    left: FITSData | np.ndarray,
    right: FITSData | np.ndarray,
    *,
    mode: ComparisonMode | str = ComparisonMode.SIDE_BY_SIDE,
    alignment: ComparisonAlignment | str = ComparisonAlignment.AUTO,
    output_dtype: Any = np.float32,
    max_output_pixels: int = DEFAULT_MAX_COMPARISON_PIXELS,
    max_working_bytes: int = DEFAULT_MAX_COMPARISON_BYTES,
    max_wcs_pixels: int = DEFAULT_MAX_WCS_REPROJECT_PIXELS,
    chunk_rows: int = DEFAULT_COMPARISON_CHUNK_ROWS,
    wcs_roundtrip_tolerance: float = DEFAULT_WCS_ROUNDTRIP_TOLERANCE,
) -> ImageComparisonResult:
    """Prepare two images for side-by-side, blink, or difference display.

    Equal-shaped inputs use direct pixel correspondence unless ``alignment`` is
    explicitly ``"wcs"``.  ``"auto"`` falls back to WCS only when shapes
    differ.  WCS alignment is intentionally restricted to two-dimensional WCS
    transforms, a bounded target grid, nearest-neighbour sampling, and a
    round-trip sanity check.  Unsupported or unreliable requests return a
    failed result with a stable ``reason_code`` instead of guessing.

    Existing source arrays are not copied for direct side-by-side/blink output.
    Any generated aligned or difference image uses ``float32`` by default and
    is produced in bounded row chunks.  Pass ``float64`` explicitly when the
    additional memory and precision are required.
    """

    parsed_mode: ComparisonMode | None = None
    try:
        parsed_mode = _parse_mode(mode)
        parsed_alignment = _parse_alignment(alignment)
        dtype = _normalize_output_dtype(output_dtype)
        pixel_limit = _positive_integer("max_output_pixels", max_output_pixels)
        byte_limit = _positive_integer("max_working_bytes", max_working_bytes)
        wcs_pixel_limit = _positive_integer("max_wcs_pixels", max_wcs_pixels)
        requested_chunk_rows = _positive_integer("chunk_rows", chunk_rows)
        roundtrip_tolerance = _positive_finite_float(
            "wcs_roundtrip_tolerance",
            wcs_roundtrip_tolerance,
        )

        left_array = _image_array(left, "left")
        right_array = _image_array(right, "right")
        _enforce_pixel_limit(left_array, "left", pixel_limit)
        _enforce_pixel_limit(right_array, "right", pixel_limit)

        if parsed_alignment is ComparisonAlignment.AUTO:
            alignment_used = (
                ComparisonAlignment.PIXEL
                if left_array.shape == right_array.shape
                else ComparisonAlignment.WCS
            )
        else:
            alignment_used = parsed_alignment

        if alignment_used is ComparisonAlignment.PIXEL:
            return _compare_on_pixel_grid(
                left_array,
                right_array,
                mode=parsed_mode,
                dtype=dtype,
                max_working_bytes=byte_limit,
                chunk_rows=requested_chunk_rows,
            )

        if left_array.size > wcs_pixel_limit:
            raise _ComparisonRejected(
                ComparisonFailureCode.OUTPUT_LIMIT,
                "WCS alignment would reproject "
                f"{left_array.size:,} pixels, above the configured limit of "
                f"{wcs_pixel_limit:,} pixels.",
            )
        return _compare_on_wcs_grid(
            left,
            right,
            left_array,
            right_array,
            mode=parsed_mode,
            dtype=dtype,
            max_working_bytes=byte_limit,
            chunk_rows=requested_chunk_rows,
            roundtrip_tolerance=roundtrip_tolerance,
        )
    except _ComparisonRejected as exc:
        shape = _safe_output_shape(left)
        return ImageComparisonResult.failure(
            exc.code,
            exc.reason,
            mode=parsed_mode,
            output_shape=shape,
        )
    except MemoryError:
        return ImageComparisonResult.failure(
            ComparisonFailureCode.MEMORY_LIMIT,
            "The comparison allocation could not be satisfied within available memory.",
            mode=parsed_mode,
            output_shape=_safe_output_shape(left),
        )


def _parse_mode(value: ComparisonMode | str) -> ComparisonMode:
    if isinstance(value, ComparisonMode):
        return value
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return ComparisonMode(normalized)
    except ValueError as exc:
        choices = ", ".join(item.value for item in ComparisonMode)
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"Unknown comparison mode {value!r}; expected one of: {choices}.",
        ) from exc


def _parse_alignment(value: ComparisonAlignment | str) -> ComparisonAlignment:
    if isinstance(value, ComparisonAlignment):
        return value
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "direct":
        normalized = ComparisonAlignment.PIXEL.value
    try:
        return ComparisonAlignment(normalized)
    except ValueError as exc:
        choices = ", ".join(item.value for item in ComparisonAlignment)
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"Unknown comparison alignment {value!r}; expected one of: {choices}.",
        ) from exc


def _normalize_output_dtype(value: Any) -> np.dtype[Any]:
    try:
        dtype = np.dtype(value)
    except (TypeError, ValueError) as exc:
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"Unsupported comparison output dtype {value!r}; use float32 or float64.",
        ) from exc
    if dtype not in (np.dtype(np.float32), np.dtype(np.float64)):
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"Unsupported comparison output dtype {dtype}; use float32 or float64.",
        )
    return dtype


def _positive_integer(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"{name} must be a positive integer.",
        )
    try:
        normalized = operator.index(value)
    except TypeError as exc:
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"{name} must be a positive integer.",
        ) from exc
    if normalized <= 0:
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"{name} must be a positive integer.",
        )
    return normalized


def _positive_finite_float(name: str, value: Any) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"{name} must be a positive finite number.",
        ) from exc
    if not math.isfinite(normalized) or normalized <= 0:
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_OPTION,
            f"{name} must be a positive finite number.",
        )
    return normalized


def _image_array(image: FITSData | np.ndarray, label: str) -> np.ndarray:
    value = image.data if isinstance(image, FITSData) else image
    if value is None:
        raise _ComparisonRejected(
            ComparisonFailureCode.MISSING_DATA,
            f"The {label} image has no pixel data.",
        )
    try:
        array = np.asarray(value)
    except Exception as exc:
        raise _ComparisonRejected(
            ComparisonFailureCode.UNSUPPORTED_DTYPE,
            f"The {label} image could not be interpreted as a numeric array: {exc}",
        ) from exc
    if array.ndim != 2 or any(size <= 0 for size in array.shape):
        raise _ComparisonRejected(
            ComparisonFailureCode.INVALID_DIMENSIONS,
            f"The {label} image must be a non-empty 2D array; got shape {array.shape}.",
        )
    if not (
        np.issubdtype(array.dtype, np.integer)
        or np.issubdtype(array.dtype, np.floating)
    ) or np.issubdtype(array.dtype, np.bool_):
        raise _ComparisonRejected(
            ComparisonFailureCode.UNSUPPORTED_DTYPE,
            f"The {label} image dtype {array.dtype} is not a supported real numeric type.",
        )
    return array


def _safe_output_shape(image: FITSData | np.ndarray) -> tuple[int, int] | None:
    try:
        value = image.data if isinstance(image, FITSData) else image
        if value is None:
            return None
        shape = np.shape(value)
        if len(shape) != 2:
            return None
        return (int(shape[0]), int(shape[1]))
    except Exception:
        return None


def _enforce_pixel_limit(array: np.ndarray, label: str, limit: int) -> None:
    if array.size > limit:
        raise _ComparisonRejected(
            ComparisonFailureCode.OUTPUT_LIMIT,
            f"The {label} image contains {array.size:,} pixels, above the configured "
            f"comparison limit of {limit:,} pixels.",
        )


def _planned_chunk_rows(
    shape: tuple[int, int],
    *,
    output_bytes: int,
    max_working_bytes: int,
    requested_rows: int,
    scratch_bytes_per_pixel: int,
) -> int:
    height, width = shape
    if output_bytes > max_working_bytes:
        raise _ComparisonRejected(
            ComparisonFailureCode.MEMORY_LIMIT,
            f"Comparison output requires {output_bytes:,} bytes, above the configured "
            f"working-memory limit of {max_working_bytes:,} bytes.",
        )
    remaining = max_working_bytes - output_bytes
    bytes_per_row = width * scratch_bytes_per_pixel
    if remaining < bytes_per_row:
        raise _ComparisonRejected(
            ComparisonFailureCode.MEMORY_LIMIT,
            "The comparison memory limit leaves insufficient space for one bounded "
            f"working row ({bytes_per_row:,} bytes required after output allocation).",
        )
    return max(1, min(height, requested_rows, remaining // bytes_per_row))


def _row_slices(height: int, rows: int):
    for start in range(0, height, rows):
        yield slice(start, min(height, start + rows))


def _finite_overlap_count(left: np.ndarray, right: np.ndarray, rows: int) -> int:
    count = 0
    for row_slice in _row_slices(left.shape[0], rows):
        valid = np.isfinite(left[row_slice])
        valid &= np.isfinite(right[row_slice])
        count += int(np.count_nonzero(valid))
    return count


def _compare_on_pixel_grid(
    left: np.ndarray,
    right: np.ndarray,
    *,
    mode: ComparisonMode,
    dtype: np.dtype[Any],
    max_working_bytes: int,
    chunk_rows: int,
) -> ImageComparisonResult:
    if left.shape != right.shape:
        raise _ComparisonRejected(
            ComparisonFailureCode.SHAPE_MISMATCH,
            f"Direct pixel comparison requires equal shapes; got {left.shape} and "
            f"{right.shape}. Select automatic or WCS alignment when both images "
            "have reliable two-dimensional WCS metadata.",
        )

    output_bytes = left.size * dtype.itemsize if mode is ComparisonMode.DIFFERENCE else 0
    rows = _planned_chunk_rows(
        left.shape,
        output_bytes=output_bytes,
        max_working_bytes=max_working_bytes,
        requested_rows=chunk_rows,
        scratch_bytes_per_pixel=32 if mode is ComparisonMode.DIFFERENCE else 4,
    )

    if mode is not ComparisonMode.DIFFERENCE:
        finite = _finite_overlap_count(left, right, rows)
        warning = None if finite else "The images have no finite overlapping pixels."
        return ImageComparisonResult(
            success=True,
            mode=mode,
            alignment_used=ComparisonAlignment.PIXEL,
            left_image=left,
            right_image=right,
            output_shape=left.shape,
            finite_overlap_pixels=finite,
            invalid_overlap_pixels=left.size - finite,
            warning=warning,
        )

    try:
        difference = np.empty(left.shape, dtype=dtype)
    except (MemoryError, ValueError) as exc:
        raise MemoryError from exc

    finite = 0
    for row_slice in _row_slices(left.shape[0], rows):
        left_block = left[row_slice]
        right_block = right[row_slice]
        output_block = difference[row_slice]
        with np.errstate(over="ignore", invalid="ignore"):
            np.subtract(
                left_block,
                right_block,
                out=output_block,
                dtype=dtype,
                casting="unsafe",
            )
        valid = np.isfinite(left_block)
        valid &= np.isfinite(right_block)
        valid &= np.isfinite(output_block)
        finite += int(np.count_nonzero(valid))
        np.copyto(output_block, np.nan, where=np.logical_not(valid))

    warning = None if finite else "The images have no finite overlapping pixels."
    return ImageComparisonResult(
        success=True,
        mode=mode,
        alignment_used=ComparisonAlignment.PIXEL,
        difference_image=difference,
        output_shape=left.shape,
        finite_overlap_pixels=finite,
        invalid_overlap_pixels=left.size - finite,
        warning=warning,
    )


def _comparison_wcs(image: FITSData | np.ndarray, label: str) -> Any:
    if not isinstance(image, FITSData) or not image.has_wcs or image.wcs is None:
        raise _ComparisonRejected(
            ComparisonFailureCode.MISSING_WCS,
            f"The {label} image has no usable WCS; WCS alignment requires both images "
            "to provide validated two-dimensional WCS metadata.",
        )
    wcs = image.wcs
    pixel_n_dim = getattr(wcs, "pixel_n_dim", 2)
    world_n_dim = getattr(wcs, "world_n_dim", 2)
    if pixel_n_dim != 2 or world_n_dim != 2:
        raise _ComparisonRejected(
            ComparisonFailureCode.UNSUPPORTED_WCS,
            f"The {label} WCS has {pixel_n_dim} pixel and {world_n_dim} world axes; "
            "only two-dimensional WCS alignment is supported.",
        )
    if not callable(getattr(wcs, "pixel_to_world_values", None)) or not callable(
        getattr(wcs, "world_to_pixel_values", None)
    ):
        raise _ComparisonRejected(
            ComparisonFailureCode.UNSUPPORTED_WCS,
            f"The {label} WCS does not expose numeric pixel/world transform methods.",
        )
    return wcs


def _coordinate_pair(values: Any, shape: tuple[int, ...], operation: str) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(values, (tuple, list)) or len(values) != 2:
        raise _ComparisonRejected(
            ComparisonFailureCode.UNSUPPORTED_WCS,
            f"{operation} returned {len(values) if isinstance(values, (tuple, list)) else 'a non-pair'} "
            "coordinates; only two-dimensional WCS is supported.",
        )
    try:
        first, second = np.broadcast_arrays(
            np.asarray(values[0], dtype=np.float64),
            np.asarray(values[1], dtype=np.float64),
        )
        first = np.broadcast_to(first, shape)
        second = np.broadcast_to(second, shape)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _ComparisonRejected(
            ComparisonFailureCode.WCS_TRANSFORM_FAILED,
            f"{operation} returned incompatible coordinate arrays: {exc}",
        ) from exc
    return first, second


def _pixel_to_world(wcs: Any, x: np.ndarray, y: np.ndarray, shape: tuple[int, ...]):
    try:
        values = wcs.pixel_to_world_values(x, y)
    except Exception as exc:
        raise _ComparisonRejected(
            ComparisonFailureCode.WCS_TRANSFORM_FAILED,
            f"WCS pixel-to-world transformation failed: {exc}",
        ) from exc
    return _coordinate_pair(values, shape, "WCS pixel-to-world transformation")


def _world_to_pixel(wcs: Any, world: tuple[np.ndarray, np.ndarray], shape: tuple[int, ...]):
    try:
        values = wcs.world_to_pixel_values(*world)
    except Exception as exc:
        raise _ComparisonRejected(
            ComparisonFailureCode.WCS_TRANSFORM_FAILED,
            f"WCS world-to-pixel transformation failed: {exc}",
        ) from exc
    return _coordinate_pair(values, shape, "WCS world-to-pixel transformation")


def _validate_wcs_roundtrip(
    left_wcs: Any,
    right_wcs: Any,
    shape: tuple[int, int],
    tolerance: float,
) -> None:
    height, width = shape
    sample_x = np.asarray([0.0, width - 1.0, 0.0, width - 1.0, (width - 1.0) / 2.0])
    sample_y = np.asarray([0.0, 0.0, height - 1.0, height - 1.0, (height - 1.0) / 2.0])
    sample_shape = sample_x.shape
    world = _pixel_to_world(left_wcs, sample_x, sample_y, sample_shape)
    right_pixel = _world_to_pixel(right_wcs, world, sample_shape)
    finite = np.isfinite(right_pixel[0]) & np.isfinite(right_pixel[1])
    if not np.any(finite):
        return
    right_world = _pixel_to_world(
        right_wcs,
        right_pixel[0][finite],
        right_pixel[1][finite],
        (int(np.count_nonzero(finite)),),
    )
    left_roundtrip = _world_to_pixel(
        left_wcs,
        right_world,
        (int(np.count_nonzero(finite)),),
    )
    expected_x = sample_x[finite]
    expected_y = sample_y[finite]
    residual = np.hypot(left_roundtrip[0] - expected_x, left_roundtrip[1] - expected_y)
    finite_residual = residual[np.isfinite(residual)]
    if finite_residual.size != residual.size:
        raise _ComparisonRejected(
            ComparisonFailureCode.WCS_UNRELIABLE,
            "WCS round-trip validation produced non-finite pixel coordinates.",
        )
    if float(np.max(finite_residual)) > tolerance:
        maximum = float(np.max(finite_residual))
        raise _ComparisonRejected(
            ComparisonFailureCode.WCS_UNRELIABLE,
            f"WCS round-trip residual reached {maximum:.3f} pixels, above the "
            f"configured reliability tolerance of {tolerance:.3f} pixels.",
        )


def _compare_on_wcs_grid(
    left_source: FITSData | np.ndarray,
    right_source: FITSData | np.ndarray,
    left: np.ndarray,
    right: np.ndarray,
    *,
    mode: ComparisonMode,
    dtype: np.dtype[Any],
    max_working_bytes: int,
    chunk_rows: int,
    roundtrip_tolerance: float,
) -> ImageComparisonResult:
    left_wcs = _comparison_wcs(left_source, "left")
    right_wcs = _comparison_wcs(right_source, "right")
    _validate_wcs_roundtrip(left_wcs, right_wcs, left.shape, roundtrip_tolerance)

    output_bytes = left.size * dtype.itemsize
    rows = _planned_chunk_rows(
        left.shape,
        output_bytes=output_bytes,
        max_working_bytes=max_working_bytes,
        requested_rows=chunk_rows,
        scratch_bytes_per_pixel=128,
    )
    try:
        output = np.full(left.shape, np.nan, dtype=dtype)
    except (MemoryError, ValueError) as exc:
        raise MemoryError from exc

    height, width = left.shape
    finite_overlap = 0
    geometric_overlap = 0
    for row_slice in _row_slices(height, rows):
        start = int(row_slice.start or 0)
        stop = int(row_slice.stop or height)
        block_shape = (stop - start, width)
        x = np.broadcast_to(np.arange(width, dtype=np.float64), block_shape)
        y = np.broadcast_to(
            np.arange(start, stop, dtype=np.float64)[:, np.newaxis],
            block_shape,
        )
        world = _pixel_to_world(left_wcs, x, y, block_shape)
        source_x, source_y = _world_to_pixel(right_wcs, world, block_shape)

        finite_coordinates = np.isfinite(source_x) & np.isfinite(source_y)
        # Bound values before converting to integer indices.  Some malformed
        # WCS transforms return finite values near the float64 limit; casting
        # those directly to int64 emits a warning and can wrap.  Coordinates
        # outside this conservative range cannot sample the right image.
        indexable = finite_coordinates
        indexable &= source_x >= -0.5
        indexable &= source_x <= right.shape[1] - 0.5
        indexable &= source_y >= -0.5
        indexable &= source_y <= right.shape[0] - 0.5
        safe_x = np.where(indexable, source_x, 0.0)
        safe_y = np.where(indexable, source_y, 0.0)
        index_x = np.rint(safe_x).astype(np.int64)
        index_y = np.rint(safe_y).astype(np.int64)
        inside = indexable
        inside &= index_x >= 0
        inside &= index_x < right.shape[1]
        inside &= index_y >= 0
        inside &= index_y < right.shape[0]
        geometric_overlap += int(np.count_nonzero(inside))

        sampled = np.full(block_shape, np.nan, dtype=dtype)
        if np.any(inside):
            sampled[inside] = right[index_y[inside], index_x[inside]]
        left_block = left[row_slice]
        valid = inside & np.isfinite(left_block) & np.isfinite(sampled)

        output_block = output[row_slice]
        if mode is ComparisonMode.DIFFERENCE:
            with np.errstate(over="ignore", invalid="ignore"):
                np.subtract(
                    left_block,
                    sampled,
                    out=output_block,
                    dtype=dtype,
                    casting="unsafe",
                )
            valid &= np.isfinite(output_block)
            np.copyto(output_block, np.nan, where=np.logical_not(valid))
        else:
            np.copyto(output_block, sampled)
            np.copyto(output_block, np.nan, where=np.logical_not(np.isfinite(sampled)))
        finite_overlap += int(np.count_nonzero(valid))

    if geometric_overlap == 0:
        raise _ComparisonRejected(
            ComparisonFailureCode.NO_OVERLAP,
            "The WCS footprints do not overlap on the left image grid.",
        )

    warning = None
    if finite_overlap == 0:
        warning = "The WCS footprints overlap, but no overlapping finite pixels are available."
    common = dict(
        success=True,
        mode=mode,
        alignment_used=ComparisonAlignment.WCS,
        output_shape=left.shape,
        finite_overlap_pixels=finite_overlap,
        invalid_overlap_pixels=left.size - finite_overlap,
        warning=warning,
    )
    if mode is ComparisonMode.DIFFERENCE:
        return ImageComparisonResult(difference_image=output, **common)
    return ImageComparisonResult(left_image=left, right_image=output, **common)
