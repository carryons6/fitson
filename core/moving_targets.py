from __future__ import annotations

from dataclasses import dataclass, replace
import csv
import math
import operator
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from .contracts import ROISelection


DEFAULT_MAX_MOVING_TARGET_FRAMES = 64
DEFAULT_MAX_MOVING_TARGET_ROI_PIXELS = 4_000_000
DEFAULT_MAX_MOVING_TARGET_STACK_BYTES = 384 * 1024**2
DEFAULT_MAX_MOVING_TARGET_SOURCES_PER_FRAME = 50_000
DEFAULT_MAX_MOVING_TARGET_TOTAL_SOURCES = 250_000
DEFAULT_MAX_MOVING_TARGET_CANDIDATES_PER_FRAME = 512
DEFAULT_MAX_MOVING_TARGET_TRACK_SEEDS = 100_000
DEFAULT_MAX_MOVING_TARGET_RAW_TRACKS = 25_000
DEFAULT_MAX_MOVING_TARGET_UNIQUE_TRACKS = 2_000
DEFAULT_MAX_MOVING_TARGET_OUTPUT_TRACKS = 1_000


_SOURCE_CATALOG_DTYPE = np.dtype(
    [("x", np.float64), ("y", np.float64), ("flux", np.float64)]
)
_CANDIDATE_CATALOG_DTYPE = np.dtype([("peak", np.float64)])


class MovingTargetError(ValueError):
    """Base error for invalid or unsupported moving-target analysis."""


class MovingTargetLimitError(MovingTargetError):
    """Raised before work would exceed a moving-target resource budget."""


class MovingTargetCancelled(RuntimeError):
    """Raised when a cooperative caller cancels core analysis."""


@dataclass(frozen=True, slots=True)
class MovingTargetParameters:
    """Validated controls for registered multi-frame moving-target detection."""

    detection_threshold: float = 5.0
    difference_threshold: float = 4.0
    min_track_hits: int = 0  # zero selects ceil(2/3 * frame_count), at least five
    min_track_speed: float = 2.0
    max_track_speed: float = 60.0
    max_track_rms: float = 0.4
    track_tolerance: float = 2.5
    recovery_tolerance: float = 4.0
    min_displacement: float = 5.0
    registration_radius: float = 25.0
    registration_source_limit: int = 2_000
    registration_max_rms: float = 1.0
    registration_min_match_fraction: float = 0.1
    static_match_radius: float = 1.6
    static_mask_radius: float = 4.0
    static_min_fraction: float = 0.6
    edge_margin: int = 12
    max_difference_area: int = 250
    max_frames: int = DEFAULT_MAX_MOVING_TARGET_FRAMES
    max_roi_pixels: int = DEFAULT_MAX_MOVING_TARGET_ROI_PIXELS
    max_stack_bytes: int = DEFAULT_MAX_MOVING_TARGET_STACK_BYTES
    max_sources_per_frame: int = DEFAULT_MAX_MOVING_TARGET_SOURCES_PER_FRAME
    max_total_sources: int = DEFAULT_MAX_MOVING_TARGET_TOTAL_SOURCES
    max_candidates_per_frame: int = DEFAULT_MAX_MOVING_TARGET_CANDIDATES_PER_FRAME
    max_track_seeds: int = DEFAULT_MAX_MOVING_TARGET_TRACK_SEEDS
    max_raw_tracks: int = DEFAULT_MAX_MOVING_TARGET_RAW_TRACKS
    max_unique_tracks: int = DEFAULT_MAX_MOVING_TARGET_UNIQUE_TRACKS
    max_output_tracks: int = DEFAULT_MAX_MOVING_TARGET_OUTPUT_TRACKS

    def validated(self, frame_count: int, shape: tuple[int, int]) -> "MovingTargetParameters":
        frames = _positive_integer("frame_count", frame_count)
        if frames < 5:
            raise MovingTargetError("Moving-target detection requires at least 5 frames.")
        height, width = (_positive_integer("height", shape[0]), _positive_integer("width", shape[1]))
        if min(height, width) < 16:
            raise MovingTargetError("Moving-target analysis requires an ROI of at least 16 x 16 pixels.")

        integer_fields = (
            "registration_source_limit",
            "edge_margin",
            "max_difference_area",
            "max_frames",
            "max_roi_pixels",
            "max_stack_bytes",
            "max_sources_per_frame",
            "max_total_sources",
            "max_candidates_per_frame",
            "max_track_seeds",
            "max_raw_tracks",
            "max_unique_tracks",
            "max_output_tracks",
        )
        normalized: dict[str, Any] = {}
        for name in integer_fields:
            value = _positive_integer(name, getattr(self, name), allow_zero=name == "edge_margin")
            normalized[name] = value

        if frames > normalized["max_frames"]:
            raise MovingTargetLimitError(
                f"Frame count {frames} exceeds the moving-target limit of {normalized['max_frames']}."
            )
        pixels = width * height
        if pixels > normalized["max_roi_pixels"]:
            raise MovingTargetLimitError(
                f"Analysis ROI contains {pixels:,} pixels; the limit is "
                f"{normalized['max_roi_pixels']:,}. Select a smaller ROI."
            )
        stack_bytes = frames * pixels * np.dtype(np.float32).itemsize
        if stack_bytes > normalized["max_stack_bytes"]:
            raise MovingTargetLimitError(
                f"The {frames}-frame ROI stack requires {stack_bytes / 1024**2:.1f} MiB; "
                f"the limit is {normalized['max_stack_bytes'] / 1024**2:.1f} MiB. "
                "Select a smaller ROI or load fewer frames."
            )

        finite_positive_fields = (
            "detection_threshold",
            "difference_threshold",
            "max_track_speed",
            "max_track_rms",
            "track_tolerance",
            "recovery_tolerance",
            "min_displacement",
            "registration_radius",
            "registration_max_rms",
            "static_match_radius",
            "static_mask_radius",
        )
        for name in finite_positive_fields:
            normalized[name] = _positive_finite(name, getattr(self, name))
        normalized["min_track_speed"] = _nonnegative_finite(
            "min_track_speed", self.min_track_speed
        )
        if normalized["min_track_speed"] >= normalized["max_track_speed"]:
            raise MovingTargetError("min_track_speed must be less than max_track_speed.")

        fraction = _positive_finite("static_min_fraction", self.static_min_fraction)
        if fraction > 1.0:
            raise MovingTargetError("static_min_fraction must be no greater than 1.")
        normalized["static_min_fraction"] = fraction

        match_fraction = _positive_finite(
            "registration_min_match_fraction", self.registration_min_match_fraction
        )
        if match_fraction > 1.0:
            raise MovingTargetError("registration_min_match_fraction must be no greater than 1.")
        normalized["registration_min_match_fraction"] = match_fraction

        if isinstance(self.min_track_hits, bool):
            raise MovingTargetError("min_track_hits must be an integer.")
        try:
            requested_hits = operator.index(self.min_track_hits)
        except TypeError as exc:
            raise MovingTargetError("min_track_hits must be an integer.") from exc
        if requested_hits < 0:
            raise MovingTargetError("min_track_hits must be zero (automatic) or positive.")
        effective_hits = max(5, int(math.ceil((2.0 / 3.0) * frames))) if requested_hits == 0 else requested_hits
        if not 5 <= effective_hits <= frames:
            raise MovingTargetError(
                f"min_track_hits must be between 5 and the frame count ({frames}), or zero for automatic."
            )
        normalized["min_track_hits"] = effective_hits
        return replace(self, **normalized)


@dataclass(slots=True)
class MovingTargetTrack:
    """One fitted trajectory and its per-frame original-image coordinates.

    ``x0``/``y0`` are the constant-velocity intercept on the registered
    reference grid (including the ROI offset). ``positions`` contains the
    corresponding coordinates in each original, unregistered frame.
    """

    target_id: int
    hit_frames: tuple[int, ...]
    x0: float
    y0: float
    vx: float
    vy: float
    rms: float
    median_snr: float
    positions: np.ndarray
    measured_mask: np.ndarray

    @property
    def hits(self) -> int:
        return len(self.hit_frames)

    @property
    def speed(self) -> float:
        return float(math.hypot(self.vx, self.vy))


@dataclass(slots=True)
class MovingTargetResult:
    """Bounded moving-target result returned to the UI and CSV exporter."""

    tracks: tuple[MovingTargetTrack, ...]
    frame_count: int
    roi: ROISelection
    seconds: np.ndarray
    time_source: str
    registration_shifts: np.ndarray
    registration_matches: tuple[int, ...]
    registration_rms: tuple[float, ...]
    source_counts: tuple[int, ...]
    candidate_counts: tuple[int, ...]
    static_source_count: int
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class _CandidateTrack:
    frame_indices: np.ndarray
    detection_indices: np.ndarray
    x0: float
    y0: float
    vx: float
    vy: float
    rms: float
    median_snr: float


class _SpatialIndex:
    """Small dependency-free uniform-grid index for 2D point queries."""

    def __init__(self, points: np.ndarray, cell_size: float) -> None:
        array = np.asarray(points, dtype=np.float64)
        if array.size == 0:
            array = np.empty((0, 2), dtype=np.float64)
        if array.ndim != 2 or array.shape[1] != 2:
            raise MovingTargetError("Spatial index points must have shape (N, 2).")
        self.points = array
        self.cell_size = max(float(cell_size), 1e-6)
        self._cells: dict[tuple[int, int], list[int]] = {}
        for index, point in enumerate(array):
            key = self._key(point)
            self._cells.setdefault(key, []).append(index)

    def _key(self, point: np.ndarray | Sequence[float]) -> tuple[int, int]:
        return (
            int(math.floor(float(point[0]) / self.cell_size)),
            int(math.floor(float(point[1]) / self.cell_size)),
        )

    def neighbors(self, point: np.ndarray | Sequence[float], radius: float) -> list[int]:
        if len(self.points) == 0:
            return []
        normalized_radius = float(radius)
        if normalized_radius < 0.0 or math.isnan(normalized_radius):
            return []
        query = np.asarray(point, dtype=np.float64)
        if query.shape != (2,) or not np.all(np.isfinite(query)):
            return []
        cx, cy = self._key(query)
        if math.isinf(normalized_radius):
            return list(range(len(self.points)))
        reach = max(1, int(math.ceil(normalized_radius / self.cell_size)))
        grid_width = 2 * reach + 1
        # A track-search radius can legitimately dwarf its small grid cells
        # when cadence or the user speed limit is large. Iterating every empty
        # cell would bypass the later seed budget, so switch to a bounded scan
        # of the actual points once the cell window is comparatively sparse.
        if grid_width * grid_width > max(64, len(self._cells) * 4):
            distances = np.hypot(
                self.points[:, 0] - query[0],
                self.points[:, 1] - query[1],
            )
            return np.flatnonzero(distances <= normalized_radius).astype(int).tolist()

        limit2 = normalized_radius * normalized_radius
        result: list[int] = []
        px, py = float(query[0]), float(query[1])
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for index in self._cells.get((gx, gy), ()):
                    dx = float(self.points[index, 0]) - px
                    dy = float(self.points[index, 1]) - py
                    if dx * dx + dy * dy <= limit2:
                        result.append(index)
        return result

    def nearest(
        self,
        point: np.ndarray | Sequence[float],
        radius: float,
    ) -> tuple[float, int]:
        candidates = self.neighbors(point, radius)
        if not candidates:
            return float("inf"), -1
        candidate_array = np.asarray(candidates, dtype=np.int64)
        delta = self.points[candidate_array] - np.asarray(point, dtype=np.float64)
        distances2 = np.sum(delta * delta, axis=1)
        local = int(np.argmin(distances2))
        return float(math.sqrt(float(distances2[local]))), int(candidate_array[local])


def _sep_module():
    import sep

    return sep


def _positive_integer(name: str, value: Any, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise MovingTargetError(f"{name} must be an integer.")
    try:
        normalized = operator.index(value)
    except TypeError as exc:
        raise MovingTargetError(f"{name} must be an integer.") from exc
    if normalized < 0 or (normalized == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise MovingTargetError(f"{name} must be {qualifier}.")
    return int(normalized)


def _positive_finite(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise MovingTargetError(f"{name} must be a finite number.")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MovingTargetError(f"{name} must be a finite number.") from exc
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise MovingTargetError(f"{name} must be a positive finite number.")
    return normalized


def _nonnegative_finite(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise MovingTargetError(f"{name} must be a finite number.")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MovingTargetError(f"{name} must be a finite number.") from exc
    if not math.isfinite(normalized) or normalized < 0.0:
        raise MovingTargetError(f"{name} must be a non-negative finite number.")
    return normalized


def _check_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise MovingTargetCancelled("Moving-target detection was cancelled.")


def _report_progress(
    callback: Callable[[int, int, str], None] | None,
    completed: int,
    total: int,
    message: str,
) -> None:
    if callback is not None:
        callback(int(completed), int(total), str(message))


def resolve_frame_times(
    headers: Sequence[Mapping[str, Any] | None],
    *,
    fallback_cadence_seconds: float,
    prefer_header_times: bool = True,
) -> tuple[np.ndarray, str, tuple[str, ...]]:
    """Resolve strictly increasing relative seconds from FITS headers or an explicit cadence."""

    frame_count = len(headers)
    if frame_count < 1:
        raise MovingTargetError("At least one frame header is required.")
    cadence = _positive_finite("fallback_cadence_seconds", fallback_cadence_seconds)
    warnings: list[str] = []
    if prefer_header_times:
        absolute_days: list[float] = []
        used_keys: list[str] = []
        time_semantics: list[str] = []
        observation_midpoints: list[bool | None] = []
        for header in headers:
            parsed = _header_time_days(header)
            if parsed is None:
                absolute_days = []
                break
            days, key, used_exposure_midpoint = parsed
            absolute_days.append(days)
            used_keys.append(key)
            time_semantics.append(_header_time_semantics(key))
            observation_midpoints.append(used_exposure_midpoint)
        if len(absolute_days) == frame_count:
            semantic_set = set(time_semantics)
            if len(semantic_set) != 1:
                labels = ", ".join(sorted(set(used_keys)))
                raise MovingTargetError(
                    "FITS timestamp semantics differ between frames "
                    f"({labels}). Use one timestamp convention for the sequence, "
                    "or disable header times and specify a fixed cadence."
                )
            if time_semantics[0] == "observation" and len(set(observation_midpoints)) != 1:
                raise MovingTargetError(
                    "FITS observation timestamps mix exposure-start and exposure-midpoint "
                    "semantics because EXPTIME/EXPOSURE is missing or invalid in some "
                    "frames. Supply valid exposure times for every frame, remove them "
                    "from every frame, or use a fixed cadence."
                )
            values = np.asarray(absolute_days, dtype=np.float64)
            seconds = (values - values[0]) * 86_400.0
            if np.all(np.isfinite(seconds)) and np.all(np.diff(seconds) > 0.0):
                if len(set(used_keys)) == 1:
                    source = used_keys[0]
                elif time_semantics[0] == "average":
                    source = "FITS average timestamps"
                elif time_semantics[0] == "observation":
                    source = (
                        "FITS exposure-midpoint timestamps"
                        if observation_midpoints[0]
                        else "FITS observation-start timestamps"
                    )
                else:
                    source = "FITS header timestamps"
                return seconds, source, ()
            raise MovingTargetError(
                "FITS timestamps must be finite, unique, and strictly increasing in "
                "the loaded frame order. Reorder the sequence, or disable header "
                "times and specify a fixed cadence."
            )
        else:
            warnings.append(
                "Not every frame has a usable FITS timestamp; "
                f"using the explicit {cadence:g} s frame cadence."
            )
    else:
        warnings.append(f"Using the user-selected fixed frame cadence of {cadence:g} s.")
    return np.arange(frame_count, dtype=np.float64) * cadence, f"Fixed cadence ({cadence:g} s)", tuple(warnings)


def _header_time_semantics(key: str) -> str:
    if key.endswith("-AVG"):
        return "average"
    if key.endswith("-OBS"):
        return "observation"
    return "generic"


def _header_time_days(
    header: Mapping[str, Any] | None,
) -> tuple[float, str, bool | None] | None:
    if header is None:
        return None
    for key, kind in (
        ("DATE-AVG", "date"),
        ("MJD-AVG", "mjd"),
        ("JD-AVG", "jd"),
        ("DATE-OBS", "date"),
        ("MJD-OBS", "mjd"),
        ("JD-OBS", "jd"),
        ("MJD", "mjd"),
        ("JD", "jd"),
    ):
        value = header.get(key)
        if value is None:
            continue
        if kind == "date":
            text = str(value).strip()
            if not text:
                continue
            if key == "DATE-OBS" and "T" not in text and " " not in text:
                time_observed = header.get("TIME-OBS")
                if time_observed is not None and str(time_observed).strip():
                    text = f"{text}T{str(time_observed).strip()}"
            try:
                from astropy.time import Time

                parsed = float(Time(text, scale="utc").mjd)
            except Exception:
                continue
        else:
            try:
                parsed = float(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if kind == "jd":
                parsed -= 2_400_000.5
        used_exposure_midpoint: bool | None = None
        if key.endswith("-OBS"):
            used_exposure_midpoint = False
            exposure = header.get("EXPTIME")
            if exposure is None:
                exposure = header.get("EXPOSURE")
            try:
                exposure_seconds = float(exposure)
            except (TypeError, ValueError, OverflowError):
                exposure_seconds = 0.0
            if math.isfinite(exposure_seconds) and exposure_seconds > 0.0:
                parsed += 0.5 * exposure_seconds / 86_400.0
                used_exposure_midpoint = True
        if math.isfinite(parsed):
            return parsed, key, used_exposure_midpoint
    return None


def _finite_float32_frame(frame: np.ndarray, frame_index: int) -> np.ndarray:
    image = np.ascontiguousarray(frame, dtype=np.float32)
    finite = np.isfinite(image)
    if not np.any(finite):
        raise MovingTargetError(f"Frame {frame_index + 1} contains no finite pixels in the analysis ROI.")
    if not np.all(finite):
        replacement = float(np.median(image[finite]))
        image[~finite] = replacement
    return image


def _extract_frame_sources(
    image: np.ndarray,
    threshold: float,
    *,
    max_sources: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    sep = _sep_module()
    background_model = sep.Background(image, bw=64, bh=64, fw=3, fh=3)
    background = np.asarray(background_model.back(), dtype=np.float32)
    residual = np.ascontiguousarray(image - background, dtype=np.float32)
    global_rms = float(background_model.globalrms)
    if not math.isfinite(global_rms) or global_rms <= 0.0:
        raise MovingTargetError("SEP reported an invalid background RMS.")
    objects = sep.extract(
        residual,
        threshold,
        err=global_rms,
        minarea=5,
        deblend_nthresh=32,
        deblend_cont=0.005,
        clean=True,
        clean_param=1.0,
    )
    if len(objects) > max_sources:
        raise MovingTargetLimitError(
            f"SEP found {len(objects):,} sources in one frame; the limit is {max_sources:,}. "
            "Increase the threshold or select a smaller ROI."
        )
    compact = np.empty(len(objects), dtype=_SOURCE_CATALOG_DTYPE)
    for field in ("x", "y", "flux"):
        compact[field] = np.asarray(objects[field], dtype=np.float64)
    return residual, compact, global_rms


def _positions(objects: np.ndarray) -> np.ndarray:
    if len(objects) == 0:
        return np.empty((0, 2), dtype=np.float64)
    return np.column_stack((objects["x"], objects["y"])).astype(np.float64, copy=False)


def _robust_catalog_shift(
    reference: np.ndarray,
    current: np.ndarray,
    *,
    radius: float,
    source_limit: int,
    max_rms: float = 1.0,
    min_match_fraction: float = 0.1,
) -> tuple[float, float, int, float]:
    ref_order = np.argsort(reference["flux"])[::-1][:source_limit]
    cur_order = np.argsort(current["flux"])[::-1][:source_limit]
    ref = _positions(reference[ref_order])
    cur = _positions(current[cur_order])
    if len(ref) < 10 or len(cur) < 10:
        raise MovingTargetError("Too few SEP sources for frame registration (need at least 10).")

    ref_index = _SpatialIndex(ref, radius)
    cur_index = _SpatialIndex(cur, radius)
    pairs: list[tuple[int, int]] = []
    for current_idx, point in enumerate(cur):
        _, reference_idx = ref_index.nearest(point, radius)
        if reference_idx < 0:
            continue
        _, reverse_idx = cur_index.nearest(ref[reference_idx], radius)
        if reverse_idx == current_idx:
            pairs.append((current_idx, reference_idx))
    required_matches = max(
        10,
        int(math.ceil(min_match_fraction * min(len(ref), len(cur)))),
    )
    if len(pairs) < required_matches:
        raise MovingTargetError(
            f"Too few mutual registration matches: {len(pairs)} "
            f"(need at least {required_matches})."
        )

    current_indices = np.fromiter((pair[0] for pair in pairs), dtype=np.int64)
    reference_indices = np.fromiter((pair[1] for pair in pairs), dtype=np.int64)
    delta = cur[current_indices] - ref[reference_indices]
    center = np.median(delta, axis=0)
    radial = np.hypot(delta[:, 0] - center[0], delta[:, 1] - center[1])
    radial_median = float(np.median(radial))
    mad = float(np.median(np.abs(radial - radial_median)))
    limit = max(0.8, radial_median + 4.0 * 1.4826 * mad)
    inlier = radial <= limit
    inlier_count = int(np.sum(inlier))
    if inlier_count < required_matches:
        raise MovingTargetError(
            "Robust registration retained only "
            f"{inlier_count} source matches (need at least {required_matches})."
        )
    center = np.median(delta[inlier], axis=0)
    rms = float(np.sqrt(np.mean(np.sum((delta[inlier] - center) ** 2, axis=1))))
    if not math.isfinite(rms) or rms > max_rms:
        raise MovingTargetError(
            f"Frame registration RMS is {rms:.3f} px; the pure-translation "
            f"limit is {max_rms:.3f} px."
        )
    return float(center[0]), float(center[1]), inlier_count, rms


def _registered_translation(image: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Sample current-frame residuals on the reference grid using bilinear translation."""

    height, width = image.shape
    pad_x = int(math.ceil(abs(dx))) + 2
    pad_y = int(math.ceil(abs(dy))) + 2
    padded = np.pad(image, ((pad_y, pad_y), (pad_x, pad_x)), mode="reflect")
    sample_x = pad_x + float(dx)
    sample_y = pad_y + float(dy)
    x0 = int(math.floor(sample_x))
    y0 = int(math.floor(sample_y))
    fx = np.float32(sample_x - x0)
    fy = np.float32(sample_y - y0)
    top_left = padded[y0 : y0 + height, x0 : x0 + width]
    top_right = padded[y0 : y0 + height, x0 + 1 : x0 + width + 1]
    bottom_left = padded[y0 + 1 : y0 + height + 1, x0 : x0 + width]
    bottom_right = padded[y0 + 1 : y0 + height + 1, x0 + 1 : x0 + width + 1]
    top = top_left * (np.float32(1.0) - fx) + top_right * fx
    bottom = bottom_left * (np.float32(1.0) - fx) + bottom_right * fx
    return np.ascontiguousarray(top * (np.float32(1.0) - fy) + bottom * fy, dtype=np.float32)


def _registered_common_bounds(
    shifts: np.ndarray,
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    """Return the half-open reference-grid area backed by real pixels in every frame."""

    values = np.asarray(shifts, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 2 or not np.all(np.isfinite(values)):
        raise MovingTargetError("Registration shifts must have shape (frames, 2) and be finite.")
    x0 = max(0.0, float(np.max(-values[:, 0])))
    y0 = max(0.0, float(np.max(-values[:, 1])))
    x1 = min(float(width), float(np.min(float(width) - values[:, 0])))
    y1 = min(float(height), float(np.min(float(height) - values[:, 1])))
    return x0, y0, x1, y1


def _persistent_static_catalog(
    catalogs: Sequence[np.ndarray],
    *,
    radius: float,
    minimum_fraction: float,
) -> tuple[np.ndarray, int]:
    reference = catalogs[len(catalogs) // 2]
    persistence = np.zeros(len(reference), dtype=np.int16)
    for points in catalogs:
        index = _SpatialIndex(points, radius)
        for reference_index, point in enumerate(reference):
            distance, _ = index.nearest(point, radius)
            if math.isfinite(distance):
                persistence[reference_index] += 1
    minimum_frames = min(
        len(catalogs),
        max(6, int(math.ceil(minimum_fraction * len(catalogs)))),
    )
    return reference[persistence >= minimum_frames], minimum_frames


def _temporal_median(
    stack: np.ndarray,
    *,
    target_chunk_bytes: int = 32 * 1024**2,
    cancel_check: Callable[[], bool] | None = None,
) -> np.ndarray:
    frames, height, width = stack.shape
    bytes_per_row = max(1, frames * width * np.dtype(np.float32).itemsize)
    chunk_rows = max(1, min(height, target_chunk_bytes // bytes_per_row))
    median = np.empty((height, width), dtype=np.float32)
    for y0 in range(0, height, chunk_rows):
        _check_cancelled(cancel_check)
        y1 = min(height, y0 + chunk_rows)
        block = np.asarray(stack[:, y0:y1, :], dtype=np.float32)
        median[y0:y1] = np.median(block, axis=0).astype(np.float32, copy=False)
    return median


def _difference_candidates(
    stack: np.ndarray,
    temporal_median: np.ndarray,
    static_catalog: np.ndarray,
    parameters: MovingTargetParameters,
    *,
    cancel_check: Callable[[], bool] | None,
    progress_callback: Callable[[int, int, str], None] | None,
    progress_offset: int,
    progress_total: int,
    valid_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[list[np.ndarray], list[np.ndarray], tuple[int, ...]]:
    sep = _sep_module()
    static_index = _SpatialIndex(static_catalog, parameters.static_mask_radius)
    candidate_positions: list[np.ndarray] = []
    candidate_objects: list[np.ndarray] = []
    candidate_counts: list[int] = []
    _, height, width = stack.shape
    valid_x0, valid_y0, valid_x1, valid_y1 = valid_bounds or (
        0.0,
        0.0,
        float(width),
        float(height),
    )
    for frame_index in range(len(stack)):
        _check_cancelled(cancel_check)
        difference = np.ascontiguousarray(stack[frame_index] - temporal_median, dtype=np.float32)
        background = sep.Background(difference, bw=64, bh=64, fw=3, fh=3)
        difference -= np.asarray(background.back(), dtype=np.float32)
        rms = float(background.globalrms)
        if not math.isfinite(rms) or rms <= 0.0:
            raise MovingTargetError(f"Difference frame {frame_index + 1} has an invalid background RMS.")
        extracted = sep.extract(
            difference,
            parameters.difference_threshold,
            err=rms,
            minarea=3,
            deblend_nthresh=16,
            deblend_cont=0.01,
            clean=True,
            clean_param=1.0,
        )
        positions = _positions(extracted)
        if len(positions):
            keep = np.ones(len(positions), dtype=bool)
            for index, point in enumerate(positions):
                distance, _ = static_index.nearest(point, parameters.static_mask_radius)
                if math.isfinite(distance):
                    keep[index] = False
            margin = parameters.edge_margin
            keep &= positions[:, 0] >= valid_x0 + margin
            keep &= positions[:, 0] < valid_x1 - margin
            keep &= positions[:, 1] >= valid_y0 + margin
            keep &= positions[:, 1] < valid_y1 - margin
            keep &= extracted["npix"] <= parameters.max_difference_area
            keep &= extracted["peak"] >= parameters.difference_threshold * rms
            positions = positions[keep]
            extracted = extracted[keep]
        if len(extracted) > parameters.max_candidates_per_frame:
            raise MovingTargetLimitError(
                f"Difference frame {frame_index + 1} produced {len(extracted):,} candidates; "
                f"the limit is {parameters.max_candidates_per_frame:,}. "
                "Increase the detection threshold or select a smaller ROI."
            )
        objects = np.empty(len(extracted), dtype=_CANDIDATE_CATALOG_DTYPE)
        objects["peak"] = np.asarray(extracted["peak"], dtype=np.float64)
        candidate_positions.append(positions)
        candidate_objects.append(objects)
        candidate_counts.append(len(objects))
        _report_progress(
            progress_callback,
            progress_offset + frame_index + 1,
            progress_total,
            f"Difference candidates {frame_index + 1}/{len(stack)}",
        )
    return candidate_positions, candidate_objects, tuple(candidate_counts)


def _fit_track(
    seed_position: np.ndarray,
    seed_velocity: np.ndarray,
    seconds: np.ndarray,
    positions: Sequence[np.ndarray],
    objects: Sequence[np.ndarray],
    indexes: Sequence[_SpatialIndex],
    tolerance: float,
) -> _CandidateTrack | None:
    x0, y0 = (float(seed_position[0]), float(seed_position[1]))
    vx, vy = (float(seed_velocity[0]), float(seed_velocity[1]))
    frame_indices: np.ndarray | None = None
    detection_indices: np.ndarray | None = None
    for _ in range(3):
        matched_frames: list[int] = []
        matched_indices: list[int] = []
        for frame_index, (time_value, index) in enumerate(zip(seconds, indexes, strict=True)):
            prediction = (x0 + vx * float(time_value), y0 + vy * float(time_value))
            distance, detection_index = index.nearest(prediction, tolerance)
            if math.isfinite(distance):
                matched_frames.append(frame_index)
                matched_indices.append(detection_index)
        if len(matched_frames) < 5:
            return None
        frame_indices = np.asarray(matched_frames, dtype=np.int64)
        detection_indices = np.asarray(matched_indices, dtype=np.int64)
        fit_times = seconds[frame_indices]
        observed = np.asarray(
            [positions[frame][detection] for frame, detection in zip(frame_indices, detection_indices, strict=True)],
            dtype=np.float64,
        )
        design = np.column_stack((np.ones(len(fit_times), dtype=np.float64), fit_times))
        x0, vx = np.linalg.lstsq(design, observed[:, 0], rcond=None)[0]
        y0, vy = np.linalg.lstsq(design, observed[:, 1], rcond=None)[0]
    assert frame_indices is not None and detection_indices is not None
    fit_times = seconds[frame_indices]
    observed = np.asarray(
        [positions[frame][detection] for frame, detection in zip(frame_indices, detection_indices, strict=True)],
        dtype=np.float64,
    )
    predicted = np.column_stack((x0 + vx * fit_times, y0 + vy * fit_times))
    residuals = np.hypot(*(observed - predicted).T)
    rms = float(np.sqrt(np.mean(residuals * residuals)))
    snr_values: list[float] = []
    for frame, detection in zip(frame_indices, detection_indices, strict=True):
        peaks = objects[frame]["peak"]
        denominator = max(1.0, float(np.median(peaks))) if len(peaks) else 1.0
        snr_values.append(float(objects[frame][detection]["peak"]) / denominator)
    return _CandidateTrack(
        frame_indices=frame_indices,
        detection_indices=detection_indices,
        x0=float(x0),
        y0=float(y0),
        vx=float(vx),
        vy=float(vy),
        rms=rms,
        median_snr=float(np.median(snr_values)),
    )


def _find_tracks(
    seconds: np.ndarray,
    positions: Sequence[np.ndarray],
    objects: Sequence[np.ndarray],
    parameters: MovingTargetParameters,
    *,
    cancel_check: Callable[[], bool] | None,
) -> list[_CandidateTrack]:
    indexes = [_SpatialIndex(points, parameters.track_tolerance) for points in positions]
    raw_tracks: list[_CandidateTrack] = []
    seed_count = 0
    for first_frame in range(len(positions) - 1):
        _check_cancelled(cancel_check)
        first_points = positions[first_frame]
        for second_frame in range(first_frame + 1, min(len(positions), first_frame + 4)):
            delta_time = float(seconds[second_frame] - seconds[first_frame])
            if delta_time <= 0.0:
                continue
            maximum_distance = parameters.max_track_speed * delta_time
            for first_position in first_points:
                neighbor_indices = indexes[second_frame].neighbors(first_position, maximum_distance)
                for second_index in neighbor_indices:
                    seed_count += 1
                    if seed_count % 256 == 0:
                        _check_cancelled(cancel_check)
                    if seed_count > parameters.max_track_seeds:
                        raise MovingTargetLimitError(
                            f"Track seed count exceeded {parameters.max_track_seeds:,}; "
                            "increase detection thresholds or select a smaller ROI."
                        )
                    second_position = positions[second_frame][second_index]
                    velocity = (second_position - first_position) / delta_time
                    speed = float(np.hypot(*velocity))
                    loose_min_speed = min(0.04, parameters.min_track_speed)
                    if not loose_min_speed <= speed <= parameters.max_track_speed:
                        continue
                    origin = first_position - velocity * float(seconds[first_frame])
                    track = _fit_track(
                        origin,
                        velocity,
                        seconds,
                        positions,
                        objects,
                        indexes,
                        parameters.track_tolerance,
                    )
                    if track is None or len(track.frame_indices) < 5:
                        continue
                    fitted_speed = float(math.hypot(track.vx, track.vy))
                    span = float(seconds[track.frame_indices[-1]] - seconds[track.frame_indices[0]])
                    if fitted_speed * span < parameters.min_displacement or track.rms > 1.8:
                        continue
                    if len(raw_tracks) >= parameters.max_raw_tracks:
                        raise MovingTargetLimitError(
                            f"Raw moving-track count exceeded {parameters.max_raw_tracks:,}; "
                            "increase detection thresholds or select a smaller ROI."
                        )
                    raw_tracks.append(track)

    raw_tracks.sort(key=lambda item: (-len(item.frame_indices), item.rms))
    unique: list[_CandidateTrack] = []
    middle_time = float(np.median(seconds))
    for raw_index, track in enumerate(raw_tracks):
        if raw_index % 64 == 0:
            _check_cancelled(cancel_check)
        middle = np.array([track.x0 + track.vx * middle_time, track.y0 + track.vy * middle_time])
        duplicate = False
        for accepted in unique:
            accepted_middle = np.array(
                [accepted.x0 + accepted.vx * middle_time, accepted.y0 + accepted.vy * middle_time]
            )
            if float(np.hypot(*(middle - accepted_middle))) >= 5.0:
                continue
            start_delta = math.hypot(track.x0 - accepted.x0, track.y0 - accepted.y0)
            end_delta = math.hypot(
                (track.x0 + track.vx * seconds[-1]) - (accepted.x0 + accepted.vx * seconds[-1]),
                (track.y0 + track.vy * seconds[-1]) - (accepted.y0 + accepted.vy * seconds[-1]),
            )
            if start_delta < 7.0 and end_delta < 7.0:
                duplicate = True
                break
        if not duplicate:
            if len(unique) >= parameters.max_unique_tracks:
                raise MovingTargetLimitError(
                    f"Unique moving-track count exceeded {parameters.max_unique_tracks:,}; "
                    "increase detection thresholds or select a smaller ROI."
                )
            unique.append(track)
    selected = [
        track
        for track in unique
        if len(track.frame_indices) >= parameters.min_track_hits
        and track.rms <= parameters.max_track_rms
        and parameters.min_track_speed <= math.hypot(track.vx, track.vy) <= parameters.max_track_speed
    ]
    if len(selected) > parameters.max_output_tracks:
        raise MovingTargetLimitError(
            f"Moving-target output contains {len(selected):,} tracks; "
            f"the limit is {parameters.max_output_tracks:,}."
        )
    return selected


def _recover_tracks(
    tracks: Sequence[_CandidateTrack],
    source_objects: Sequence[np.ndarray],
    shifts: np.ndarray,
    seconds: np.ndarray,
    roi: ROISelection,
    tolerance: float,
    static_catalog: np.ndarray,
    static_exclusion_radius: float,
) -> tuple[MovingTargetTrack, ...]:
    """Recover SEP centroids with a one-source/one-track assignment per frame."""

    ordered_tracks = sorted(tracks, key=lambda item: item.x0)
    source_positions = [_positions(objects) for objects in source_objects]
    frame_count = len(seconds)
    recovered_positions = np.empty((len(ordered_tracks), frame_count, 2), dtype=np.float64)
    recovered_measured = np.zeros((len(ordered_tracks), frame_count), dtype=bool)
    static_index = _SpatialIndex(static_catalog, static_exclusion_radius)

    for frame_index, (time_value, shift, raw_sources) in enumerate(
        zip(seconds, shifts, source_positions, strict=True)
    ):
        source_index = _SpatialIndex(raw_sources, tolerance)
        eligible = np.ones(len(raw_sources), dtype=bool)
        for source_number, raw_source in enumerate(raw_sources):
            distance, _ = static_index.nearest(
                raw_source - shift,
                static_exclusion_radius,
            )
            if math.isfinite(distance):
                eligible[source_number] = False

        assignment_candidates: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(ordered_tracks):
            aligned_prediction = np.array(
                [track.x0 + track.vx * time_value, track.y0 + track.vy * time_value],
                dtype=np.float64,
            )
            raw_prediction = aligned_prediction + shift
            recovered_positions[track_index, frame_index] = raw_prediction
            for source_number in source_index.neighbors(raw_prediction, tolerance):
                if not eligible[source_number]:
                    continue
                distance = float(np.hypot(*(raw_sources[source_number] - raw_prediction)))
                assignment_candidates.append((distance, track_index, source_number))

        assigned_tracks: set[int] = set()
        assigned_sources: set[int] = set()
        for _, track_index, source_number in sorted(assignment_candidates):
            if track_index in assigned_tracks or source_number in assigned_sources:
                continue
            recovered_positions[track_index, frame_index] = raw_sources[source_number]
            recovered_measured[track_index, frame_index] = True
            assigned_tracks.add(track_index)
            assigned_sources.add(source_number)

    recovered: list[MovingTargetTrack] = []
    for target_index, track in enumerate(ordered_tracks, start=1):
        positions = recovered_positions[target_index - 1]
        measured = recovered_measured[target_index - 1]
        positions[:, 0] += roi.x0
        positions[:, 1] += roi.y0
        recovered.append(
            MovingTargetTrack(
                target_id=target_index,
                hit_frames=tuple(int(value) for value in track.frame_indices),
                x0=track.x0 + roi.x0,
                y0=track.y0 + roi.y0,
                vx=track.vx,
                vy=track.vy,
                rms=track.rms,
                median_snr=track.median_snr,
                positions=positions,
                measured_mask=measured,
            )
        )
    return tuple(recovered)


def detect_moving_targets(
    frame_stack: np.ndarray,
    seconds: Sequence[float],
    *,
    roi: ROISelection | None = None,
    parameters: MovingTargetParameters | None = None,
    time_source: str = "Relative seconds",
    warnings: Sequence[str] = (),
    in_place: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> MovingTargetResult:
    """Detect obvious linear movers in an already-loaded, equal-shaped frame stack.

    The pipeline follows the validated handoff method: per-frame SEP extraction,
    robust stellar translation, registered temporal-median subtraction, static
    masking, constant-velocity association, and recovery against the original
    SEP centroids. When ``in_place`` is true the float32 stack is used as scratch
    storage; callers must pass a writable private array or memmap.
    """

    array = np.asanyarray(frame_stack)
    if array.ndim != 3:
        raise MovingTargetError("frame_stack must have shape (frames, height, width).")
    if np.issubdtype(array.dtype, np.complexfloating):
        raise MovingTargetError("frame_stack must contain real-valued image data.")
    frame_count, height, width = (int(value) for value in array.shape)
    request = (parameters or MovingTargetParameters()).validated(frame_count, (height, width))
    if roi is None:
        roi = ROISelection(x0=0, y0=0, width=width, height=height)
    if roi.width != width or roi.height != height or roi.x0 < 0 or roi.y0 < 0:
        raise MovingTargetError("ROI metadata must match the supplied frame-stack dimensions.")

    time_values = np.asarray(seconds, dtype=np.float64)
    if time_values.shape != (frame_count,) or not np.all(np.isfinite(time_values)):
        raise MovingTargetError("seconds must contain one finite value per frame.")
    time_values = time_values - time_values[0]
    if not np.all(np.diff(time_values) > 0.0):
        raise MovingTargetError("Frame times must be strictly increasing.")

    _check_cancelled(cancel_check)
    if in_place:
        if array.dtype != np.float32 or not array.dtype.isnative or not array.flags.writeable:
            raise MovingTargetError("in_place analysis requires a writable native float32 stack.")
        work = array
    else:
        work = np.array(array, dtype=np.float32, order="C", copy=True)

    total_progress = frame_count * 3 + 3
    source_objects: list[np.ndarray] = []
    source_counts: list[int] = []
    total_sources = 0
    for frame_index in range(frame_count):
        _check_cancelled(cancel_check)
        image = _finite_float32_frame(work[frame_index], frame_index)
        residual, objects, _ = _extract_frame_sources(
            image,
            request.detection_threshold,
            max_sources=request.max_sources_per_frame,
        )
        total_sources += len(objects)
        if total_sources > request.max_total_sources:
            raise MovingTargetLimitError(
                f"SEP found more than {request.max_total_sources:,} sources across the "
                "sequence; increase the threshold or select a smaller ROI."
            )
        work[frame_index] = residual
        source_objects.append(objects)
        source_counts.append(len(objects))
        _report_progress(
            progress_callback,
            frame_index + 1,
            total_progress,
            f"SEP extraction {frame_index + 1}/{frame_count}",
        )

    reference_index = frame_count // 2
    reference_objects = source_objects[reference_index]
    shifts = np.empty((frame_count, 2), dtype=np.float64)
    registration_matches: list[int] = []
    registration_rms: list[float] = []
    for frame_index, objects in enumerate(source_objects):
        _check_cancelled(cancel_check)
        if frame_index == reference_index:
            dx = dy = rms = 0.0
            matches = min(len(objects), request.registration_source_limit)
        else:
            dx, dy, matches, rms = _robust_catalog_shift(
                reference_objects,
                objects,
                radius=request.registration_radius,
                source_limit=request.registration_source_limit,
                max_rms=request.registration_max_rms,
                min_match_fraction=request.registration_min_match_fraction,
            )
            compared_sources = min(
                len(reference_objects),
                len(objects),
                request.registration_source_limit,
            )
            required_matches = max(
                10,
                int(math.ceil(request.registration_min_match_fraction * compared_sources)),
            )
            if matches < required_matches:
                raise MovingTargetError(
                    f"Frame {frame_index + 1} registration retained {matches} matches; "
                    f"at least {required_matches} are required."
                )
            if not math.isfinite(rms) or rms > request.registration_max_rms:
                raise MovingTargetError(
                    f"Frame {frame_index + 1} registration RMS is {rms:.3f} px; "
                    f"the limit is {request.registration_max_rms:.3f} px."
                )
            if not (math.isfinite(dx) and math.isfinite(dy)):
                raise MovingTargetError(
                    f"Frame {frame_index + 1} registration returned a non-finite shift."
                )
        shifts[frame_index] = (dx, dy)
        registration_matches.append(matches)
        registration_rms.append(rms)
        if frame_index != reference_index:
            work[frame_index] = _registered_translation(work[frame_index], dx, dy)
        _report_progress(
            progress_callback,
            frame_count + frame_index + 1,
            total_progress,
            f"Frame registration {frame_index + 1}/{frame_count}",
        )

    aligned_catalogs = [
        _positions(objects) - shift
        for objects, shift in zip(source_objects, shifts, strict=True)
    ]
    static_catalog, _ = _persistent_static_catalog(
        aligned_catalogs,
        radius=request.static_match_radius,
        minimum_fraction=request.static_min_fraction,
    )
    del aligned_catalogs
    _check_cancelled(cancel_check)
    temporal_median = _temporal_median(work, cancel_check=cancel_check)
    _report_progress(
        progress_callback,
        frame_count * 2 + 1,
        total_progress,
        "Temporal median ready",
    )
    candidate_positions, candidate_objects, candidate_counts = _difference_candidates(
        work,
        temporal_median,
        static_catalog,
        request,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
        progress_offset=frame_count * 2 + 1,
        progress_total=total_progress,
        valid_bounds=_registered_common_bounds(shifts, width, height),
    )
    del temporal_median

    _check_cancelled(cancel_check)
    candidates = _find_tracks(
        time_values,
        candidate_positions,
        candidate_objects,
        request,
        cancel_check=cancel_check,
    )
    _report_progress(
        progress_callback,
        frame_count * 3 + 2,
        total_progress,
        "Linear tracks fitted",
    )
    tracks = _recover_tracks(
        candidates,
        source_objects,
        shifts,
        time_values,
        roi,
        request.recovery_tolerance,
        static_catalog,
        request.static_match_radius,
    )
    _report_progress(
        progress_callback,
        total_progress,
        total_progress,
        "Moving-target detection complete",
    )
    return MovingTargetResult(
        tracks=tracks,
        frame_count=frame_count,
        roi=roi,
        seconds=time_values,
        time_source=str(time_source),
        registration_shifts=shifts,
        registration_matches=tuple(registration_matches),
        registration_rms=tuple(registration_rms),
        source_counts=tuple(source_counts),
        candidate_counts=candidate_counts,
        static_source_count=len(static_catalog),
        warnings=tuple(str(item) for item in warnings),
    )


class MovingTargetService:
    """Small service wrapper around :func:`detect_moving_targets`."""

    def detect(self, frame_stack: np.ndarray, seconds: Sequence[float], **kwargs: Any) -> MovingTargetResult:
        return detect_moving_targets(frame_stack, seconds, **kwargs)


def export_moving_targets_csv(result: MovingTargetResult, path: str | Path) -> None:
    """Export one row per target and frame with fitted trajectory metadata."""

    fieldnames = [
        "Target",
        "Frame",
        "TimeSeconds",
        "X",
        "Y",
        "MeasuredSEP",
        "VX",
        "VY",
        "Speed",
        "TrackRMS",
        "DifferenceHits",
        "TimeSource",
    ]
    with open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for track in result.tracks:
            for frame_index, (position, measured) in enumerate(
                zip(track.positions, track.measured_mask, strict=True)
            ):
                writer.writerow(
                    {
                        "Target": f"T{track.target_id}",
                        "Frame": frame_index + 1,
                        "TimeSeconds": f"{float(result.seconds[frame_index]):.9f}",
                        "X": f"{float(position[0]):.6f}",
                        "Y": f"{float(position[1]):.6f}",
                        "MeasuredSEP": int(bool(measured)),
                        "VX": f"{track.vx:.9f}",
                        "VY": f"{track.vy:.9f}",
                        "Speed": f"{track.speed:.9f}",
                        "TrackRMS": f"{track.rms:.9f}",
                        "DifferenceHits": track.hits,
                        "TimeSource": result.time_source,
                    }
                )


__all__ = [
    "DEFAULT_MAX_MOVING_TARGET_CANDIDATES_PER_FRAME",
    "DEFAULT_MAX_MOVING_TARGET_FRAMES",
    "DEFAULT_MAX_MOVING_TARGET_OUTPUT_TRACKS",
    "DEFAULT_MAX_MOVING_TARGET_RAW_TRACKS",
    "DEFAULT_MAX_MOVING_TARGET_ROI_PIXELS",
    "DEFAULT_MAX_MOVING_TARGET_SOURCES_PER_FRAME",
    "DEFAULT_MAX_MOVING_TARGET_STACK_BYTES",
    "DEFAULT_MAX_MOVING_TARGET_TRACK_SEEDS",
    "DEFAULT_MAX_MOVING_TARGET_TOTAL_SOURCES",
    "DEFAULT_MAX_MOVING_TARGET_UNIQUE_TRACKS",
    "MovingTargetCancelled",
    "MovingTargetError",
    "MovingTargetLimitError",
    "MovingTargetParameters",
    "MovingTargetResult",
    "MovingTargetService",
    "MovingTargetTrack",
    "detect_moving_targets",
    "export_moving_targets_csv",
    "resolve_frame_times",
]
