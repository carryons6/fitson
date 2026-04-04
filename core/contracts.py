from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class OpenFileRequest:
    """Request payload for opening a FITS file."""

    path: str
    hdu_index: int | None = None


@dataclass(slots=True)
class RenderRequest:
    """Request payload for generating a display image."""

    stretch_name: str
    interval_name: str
    manual_vmin: float | None = None
    manual_vmax: float | None = None


@dataclass(slots=True)
class RenderResult:
    """Display-oriented render output produced by FITSService."""

    image_u8: np.ndarray | None
    width: int = 0
    height: int = 0
    invalid_pixels: bool = False


@dataclass(slots=True)
class ROISelection:
    """Image-space rectangular selection used for SEP extraction."""

    x0: int
    y0: int
    width: int
    height: int


@dataclass(slots=True)
class PixelSample:
    """Status-bar data sampled from the current image position."""

    x: int | None = None
    y: int | None = None
    value: float | None = None
    ra: str | None = None
    dec: str | None = None
    inside_image: bool = False


@dataclass(slots=True)
class ZoomState:
    """Current view zoom state reported by the canvas."""

    scale_factor: float = 1.0
    mode: str = "custom"
