"""Coordinate transforms shared by image display, overlays and selections.

An orientation is (horizontal flip, vertical flip, transpose). Transpose is
applied first. Pixel centers are indexed from 0 to size - 1; half-open ROI
edges range from 0 to size. Keeping these two spaces explicit avoids moving
flipped rectangles by one pixel.
"""

from __future__ import annotations

Orientation = tuple[bool, bool, bool]
IDENTITY: Orientation = (False, False, False)


def display_dimensions(width: int, height: int, orientation: Orientation) -> tuple[int, int]:
    return (height, width) if orientation[2] else (width, height)


def _orient(
    x: float, y: float, width: int, height: int, orientation: Orientation, *, edge: bool
) -> tuple[float, float]:
    horizontal, vertical, transpose = orientation
    if transpose:
        x, y = y, x
        width, height = height, width
    offset = 0 if edge else 1
    if horizontal:
        x = width - offset - x
    if vertical:
        y = height - offset - y
    return x, y


def _unorient(
    x: float, y: float, width: int, height: int, orientation: Orientation, *, edge: bool
) -> tuple[float, float]:
    horizontal, vertical, transpose = orientation
    displayed_width, displayed_height = display_dimensions(width, height, orientation)
    offset = 0 if edge else 1
    if horizontal:
        x = displayed_width - offset - x
    if vertical:
        y = displayed_height - offset - y
    return (y, x) if transpose else (x, y)


def orient_point(
    x: float, y: float, width: int, height: int, orientation: Orientation
) -> tuple[float, float]:
    """Map a pixel center in the original image to displayed coordinates."""
    return _orient(x, y, width, height, orientation, edge=False)


def unorient_point(
    x: float, y: float, width: int, height: int, orientation: Orientation
) -> tuple[float, float]:
    """Map a displayed pixel center back using the original image dimensions."""
    return _unorient(x, y, width, height, orientation, edge=False)


def orient_edge_point(
    x: float, y: float, width: int, height: int, orientation: Orientation
) -> tuple[float, float]:
    """Map a half-open rectangle edge to displayed image edges."""
    return _orient(x, y, width, height, orientation, edge=True)


def unorient_edge_point(
    x: float, y: float, width: int, height: int, orientation: Orientation
) -> tuple[float, float]:
    """Map a displayed rectangle edge back to original image edges."""
    return _unorient(x, y, width, height, orientation, edge=True)


def axis_directions(orientation: Orientation) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return displayed unit direction vectors of the original +X and +Y axes."""
    origin = orient_point(0.0, 0.0, 1, 1, orientation)
    x_point = orient_point(1.0, 0.0, 1, 1, orientation)
    y_point = orient_point(0.0, 1.0, 1, 1, orientation)
    return (
        (x_point[0] - origin[0], x_point[1] - origin[1]),
        (y_point[0] - origin[0], y_point[1] - origin[1]),
    )
