from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

import numpy as np

from ..core.ds9_regions import DS9Attribute, DS9Region, DS9RegionDocument


MAX_RENDERED_REGIONS = 2_000
MAX_RENDERED_POINTS = 100_000
CURVE_SAMPLES = 64


@dataclass(frozen=True, slots=True)
class DS9OverlayBuildResult:
    overlays: tuple[dict[str, Any], ...]
    skipped_regions: int = 0
    skipped_without_wcs: int = 0
    physical_as_image_regions: int = 0


def _last_attribute(attributes: tuple[DS9Attribute, ...], *names: str) -> str | None:
    accepted = frozenset(name.lower() for name in names)
    for attribute in reversed(attributes):
        if attribute.name in accepted:
            return attribute.value
    return None


def _pixel_curve(region: DS9Region) -> tuple[list[tuple[float, float]], bool, bool]:
    params = region.parameters
    shape = region.shape
    if shape == "point":
        return [(params[0] - 1.0, params[1] - 1.0)], False, True
    if shape == "polygon":
        return [(params[i] - 1.0, params[i + 1] - 1.0) for i in range(0, len(params), 2)], True, False

    center_x, center_y = params[0] - 1.0, params[1] - 1.0
    angle = math.radians(params[4] if len(params) == 5 else 0.0)
    if shape == "box":
        half_width, half_height = params[2] * 0.5, params[3] * 0.5
        local = [
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
        ]
    else:
        radius_x = params[2]
        radius_y = params[2] if shape == "circle" else params[3]
        local = [
            (
                radius_x * math.cos(2.0 * math.pi * index / CURVE_SAMPLES),
                radius_y * math.sin(2.0 * math.pi * index / CURVE_SAMPLES),
            )
            for index in range(CURVE_SAMPLES)
        ]
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    return [
        (
            center_x + dx * cos_angle - dy * sin_angle,
            center_y + dx * sin_angle + dy * cos_angle,
        )
        for dx, dy in local
    ], True, False


def _skycoord(center_ra: float, center_dec: float, system: str):
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    return SkyCoord(ra=center_ra * u.deg, dec=center_dec * u.deg, frame=system).icrs


def _sky_offset_points(
    center_ra: float,
    center_dec: float,
    offsets: list[tuple[float, float]],
    system: str,
) -> tuple[np.ndarray, np.ndarray]:
    import astropy.units as u

    center = _skycoord(center_ra, center_dec, system)
    east = np.asarray([point[0] for point in offsets], dtype=float)
    north = np.asarray([point[1] for point in offsets], dtype=float)
    separation = np.hypot(east, north)
    position_angle = np.arctan2(east, north)
    coordinates = center.directional_offset_by(position_angle * u.rad, separation * u.deg)
    return np.asarray(coordinates.ra.deg), np.asarray(coordinates.dec.deg)


def _celestial_curve(
    region: DS9Region,
    wcs: Any,
) -> tuple[list[tuple[float, float]], bool, bool]:
    params = region.parameters
    shape = region.shape
    system = region.coordinate_system
    if shape == "polygon":
        from astropy.coordinates import SkyCoord
        import astropy.units as u

        coordinates = SkyCoord(
            ra=np.asarray(params[0::2]) * u.deg,
            dec=np.asarray(params[1::2]) * u.deg,
            frame=system,
        ).icrs
        ra, dec = coordinates.ra.deg, coordinates.dec.deg
        closed, point = True, False
    elif shape == "point":
        center = _skycoord(params[0], params[1], system)
        ra, dec = np.asarray([center.ra.deg]), np.asarray([center.dec.deg])
        closed, point = False, True
    else:
        angle = math.radians(params[4] if len(params) == 5 else 0.0)
        if shape == "box":
            radius_x, radius_y = params[2] * 0.5, params[3] * 0.5
            local = [
                (-radius_x, -radius_y),
                (radius_x, -radius_y),
                (radius_x, radius_y),
                (-radius_x, radius_y),
            ]
        else:
            radius_x = params[2]
            radius_y = params[2] if shape == "circle" else params[3]
            local = [
                (
                    radius_x * math.cos(2.0 * math.pi * index / CURVE_SAMPLES),
                    radius_y * math.sin(2.0 * math.pi * index / CURVE_SAMPLES),
                )
                for index in range(CURVE_SAMPLES)
            ]
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)
        offsets = [
            (dx * cos_angle - dy * sin_angle, dx * sin_angle + dy * cos_angle)
            for dx, dy in local
        ]
        ra, dec = _sky_offset_points(params[0], params[1], offsets, system)
        closed, point = True, False
    x, y = wcs.world_to_pixel_values(ra, dec)
    xs = np.asarray(x, dtype=float).reshape(-1)
    ys = np.asarray(y, dtype=float).reshape(-1)
    if xs.size != ys.size or xs.size == 0 or not np.all(np.isfinite(xs) & np.isfinite(ys)):
        raise ValueError("Region WCS projection produced non-finite pixels.")
    return list(zip(xs.tolist(), ys.tolist())), closed, point


def _clip_polygon(
    points: list[tuple[float, float]],
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> list[tuple[float, float]]:
    output = points
    edges = (
        (lambda p: p[0] >= left, lambda a, b: (left, a[1] + (b[1] - a[1]) * (left - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= right, lambda a, b: (right, a[1] + (b[1] - a[1]) * (right - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= top, lambda a, b: (a[0] + (b[0] - a[0]) * (top - a[1]) / (b[1] - a[1]), top)),
        (lambda p: p[1] <= bottom, lambda a, b: (a[0] + (b[0] - a[0]) * (bottom - a[1]) / (b[1] - a[1]), bottom)),
    )
    for inside, intersection in edges:
        if not output:
            break
        source = output
        output = []
        previous = source[-1]
        previous_inside = inside(previous)
        for current in source:
            current_inside = inside(current)
            if current_inside != previous_inside:
                try:
                    output.append(intersection(previous, current))
                except ZeroDivisionError:
                    pass
            if current_inside:
                output.append(current)
            previous, previous_inside = current, current_inside
    return output


def build_ds9_overlays(
    document: DS9RegionDocument,
    *,
    width: int,
    height: int,
    wcs: Any = None,
    point_transform: Callable[[float, float], tuple[float, float]] | None = None,
    max_regions: int = MAX_RENDERED_REGIONS,
    max_points: int = MAX_RENDERED_POINTS,
) -> DS9OverlayBuildResult:
    """Project a bounded DS9 document into safe, clipped canvas geometry."""

    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("Region overlay requires positive image dimensions.")
    max_regions = max(1, min(int(max_regions), MAX_RENDERED_REGIONS))
    max_points = max(1, min(int(max_points), MAX_RENDERED_POINTS))
    transform = point_transform or (lambda x, y: (x, y))
    margin = min(64.0, max(4.0, max(width, height) * 0.02))
    clip_bounds = (-margin, -margin, width - 1.0 + margin, height - 1.0 + margin)

    overlays: list[dict[str, Any]] = []
    skipped = 0
    skipped_without_wcs = 0
    physical_count = 0
    used_points = 0
    for index, region in enumerate(document.regions):
        if len(overlays) >= max_regions:
            skipped += len(document.regions) - index
            break
        try:
            if region.coordinate_system in {"fk5", "icrs"}:
                if wcs is None:
                    skipped_without_wcs += 1
                    continue
                points, closed, is_point = _celestial_curve(region, wcs)
            else:
                points, closed, is_point = _pixel_curve(region)
                if region.coordinate_system == "physical":
                    physical_count += 1
        except Exception:
            skipped += 1
            continue

        if is_point:
            x, y = points[0]
            if not (clip_bounds[0] <= x <= clip_bounds[2] and clip_bounds[1] <= y <= clip_bounds[3]):
                skipped += 1
                continue
        else:
            points = _clip_polygon(points, *clip_bounds)
            if len(points) < 3:
                skipped += 1
                continue
        if used_points + len(points) > max_points:
            skipped += 1
            continue
        used_points += len(points)
        display_points = [transform(x, y) for x, y in points]
        if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in display_points):
            skipped += 1
            continue

        attributes = document.effective_attributes(region)
        label = _last_attribute(attributes, "text", "label") or ""
        color = _last_attribute(attributes, "color") or ("green" if region.include else "red")
        width_value = _last_attribute(attributes, "width") or "1"
        try:
            line_width = max(1, min(int(float(width_value)), 10))
        except (TypeError, ValueError, OverflowError):
            line_width = 1
        overlays.append(
            {
                "index": index,
                "points": display_points,
                "closed": closed,
                "point": is_point,
                "include": region.include,
                "color": color,
                "width": line_width,
                "label": label,
                "tooltip": f"DS9 {region.coordinate_system} {region.shape} #{index + 1}",
            }
        )

    return DS9OverlayBuildResult(
        overlays=tuple(overlays),
        skipped_regions=skipped,
        skipped_without_wcs=skipped_without_wcs,
        physical_as_image_regions=physical_count,
    )


__all__ = [
    "CURVE_SAMPLES",
    "DS9OverlayBuildResult",
    "MAX_RENDERED_POINTS",
    "MAX_RENDERED_REGIONS",
    "build_ds9_overlays",
]
