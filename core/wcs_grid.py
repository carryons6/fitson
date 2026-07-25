from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

import numpy as np


MAX_GRID_LINES_PER_AXIS = 12
MAX_GRID_SAMPLES_PER_LINE = 128


@dataclass(frozen=True, slots=True)
class WCSGridLine:
    axis: str
    world_value_deg: float
    label: str
    segments: tuple[tuple[tuple[float, float], ...], ...]


@dataclass(frozen=True, slots=True)
class WCSGrid:
    lines: tuple[WCSGridLine, ...]
    center_ra_deg: float
    center_dec_deg: float
    field_radius_deg: float


def _nice_step(span: float, target_lines: int = 6) -> float:
    if not math.isfinite(span) or span <= 0:
        return 1.0
    raw = span / max(2, target_lines)
    exponent = 10.0 ** math.floor(math.log10(raw))
    scaled = raw / exponent
    multiplier = 1.0 if scaled <= 1.0 else 2.0 if scaled <= 2.0 else 5.0 if scaled <= 5.0 else 10.0
    return multiplier * exponent


def _format_ra(ra_deg: float) -> str:
    total_seconds = (ra_deg % 360.0) * 240.0
    hours = int(total_seconds // 3600) % 24
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    if seconds < 0.05:
        return f"{hours:02d}h{minutes:02d}m"
    return f"{hours:02d}h{minutes:02d}m{seconds:04.1f}s"


def _format_dec(dec_deg: float) -> str:
    sign = "+" if dec_deg >= 0 else "−"
    absolute = abs(dec_deg)
    degrees = int(absolute)
    minutes = int(round((absolute - degrees) * 60.0))
    if minutes == 60:
        degrees += 1
        minutes = 0
    return f"{sign}{degrees:02d}°{minutes:02d}′"


def _world_values(wcs: Any, x: Iterable[float], y: Iterable[float]) -> tuple[np.ndarray, np.ndarray]:
    ra, dec = wcs.pixel_to_world_values(np.asarray(tuple(x), dtype=float), np.asarray(tuple(y), dtype=float))
    return np.asarray(ra, dtype=float), np.asarray(dec, dtype=float)


def _pixel_values(wcs: Any, ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x, y = wcs.world_to_pixel_values(np.asarray(ra, dtype=float), np.asarray(dec, dtype=float))
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _split_visible_segments(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    width: int,
    height: int,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    margin = max(width, height) * 0.08 + 2.0
    max_jump = max(width, height) * 0.35 + 4.0
    segments: list[tuple[tuple[float, float], ...]] = []
    current: list[tuple[float, float]] = []
    previous: tuple[float, float] | None = None
    for x, y in zip(xs.tolist(), ys.tolist()):
        point = (float(x), float(y))
        visible = (
            math.isfinite(point[0])
            and math.isfinite(point[1])
            and -margin <= point[0] <= width - 1 + margin
            and -margin <= point[1] <= height - 1 + margin
        )
        discontinuity = previous is not None and math.hypot(point[0] - previous[0], point[1] - previous[1]) > max_jump
        if not visible or discontinuity:
            if len(current) >= 2:
                segments.append(tuple(current))
            current = []
            previous = None
            continue
        current.append(point)
        previous = point
    if len(current) >= 2:
        segments.append(tuple(current))
    return tuple(segments)


def _grid_values(low: float, high: float, step: float) -> list[float]:
    start = math.ceil(low / step) * step
    values: list[float] = []
    value = start
    while value <= high + step * 1e-8 and len(values) < MAX_GRID_LINES_PER_AXIS:
        values.append(value)
        value += step
    return values


def build_wcs_grid(
    wcs: Any,
    width: int,
    height: int,
    *,
    target_lines: int = 6,
    samples_per_line: int = 96,
) -> WCSGrid:
    """Project a bounded RA/Dec grid into original FITS pixel coordinates."""

    width, height = int(width), int(height)
    if width <= 1 or height <= 1:
        raise ValueError("WCS grid requires an image at least 2 by 2 pixels.")
    target_lines = max(2, min(int(target_lines), MAX_GRID_LINES_PER_AXIS))
    samples_per_line = max(16, min(int(samples_per_line), MAX_GRID_SAMPLES_PER_LINE))

    border_samples = 17
    top_x = np.linspace(0.0, width - 1.0, border_samples)
    side_y = np.linspace(0.0, height - 1.0, border_samples)
    xs = np.concatenate((top_x, np.full(border_samples, width - 1.0), top_x[::-1], np.zeros(border_samples)))
    ys = np.concatenate((np.zeros(border_samples), side_y, np.full(border_samples, height - 1.0), side_y[::-1]))
    ras, decs = _world_values(wcs, xs, ys)
    finite = np.isfinite(ras) & np.isfinite(decs) & (decs >= -90.0) & (decs <= 90.0)
    if int(np.count_nonzero(finite)) < 4:
        raise ValueError("WCS does not map enough image-border samples to sky coordinates.")

    center_ra_values, center_dec_values = _world_values(wcs, (0.5 * (width - 1),), (0.5 * (height - 1),))
    center_ra = float(center_ra_values[0]) % 360.0
    center_dec = float(center_dec_values[0])
    if not (math.isfinite(center_ra) and math.isfinite(center_dec)):
        raise ValueError("WCS image center is not finite.")

    ra_unwrapped = center_ra + np.rad2deg(
        np.unwrap(np.deg2rad(ras[finite] - center_ra), discont=np.pi)
    )
    # Reduce every sample to the nearest wrap around the center.  np.unwrap
    # follows border order; this second normalization prevents a final border
    # crossing from inflating the span by 360 degrees.
    ra_unwrapped = center_ra + ((ra_unwrapped - center_ra + 180.0) % 360.0) - 180.0
    dec_finite = decs[finite]
    ra_low, ra_high = float(np.min(ra_unwrapped)), float(np.max(ra_unwrapped))
    dec_low, dec_high = float(np.min(dec_finite)), float(np.max(dec_finite))
    if ra_high <= ra_low or dec_high <= dec_low:
        raise ValueError("WCS sky footprint is degenerate.")

    ra_step = _nice_step(ra_high - ra_low, target_lines)
    dec_step = _nice_step(dec_high - dec_low, target_lines)
    lines: list[WCSGridLine] = []

    dec_samples = np.linspace(dec_low, dec_high, samples_per_line)
    for ra_value in _grid_values(ra_low, ra_high, ra_step):
        ra_samples = np.full(samples_per_line, ra_value % 360.0)
        px, py = _pixel_values(wcs, ra_samples, dec_samples)
        segments = _split_visible_segments(px, py, width=width, height=height)
        if segments:
            lines.append(WCSGridLine("ra", ra_value % 360.0, _format_ra(ra_value), segments))

    ra_samples_unwrapped = np.linspace(ra_low, ra_high, samples_per_line)
    ra_samples = np.mod(ra_samples_unwrapped, 360.0)
    for dec_value in _grid_values(dec_low, dec_high, dec_step):
        dec_samples_fixed = np.full(samples_per_line, dec_value)
        px, py = _pixel_values(wcs, ra_samples, dec_samples_fixed)
        segments = _split_visible_segments(px, py, width=width, height=height)
        if segments:
            lines.append(WCSGridLine("dec", dec_value, _format_dec(dec_value), segments))

    angular_offsets = np.hypot(
        (ra_unwrapped - center_ra) * max(math.cos(math.radians(center_dec)), 1e-6),
        dec_finite - center_dec,
    )
    field_radius = float(np.max(angular_offsets)) if angular_offsets.size else 0.0
    return WCSGrid(tuple(lines), center_ra, center_dec, field_radius)
