from __future__ import annotations

from dataclasses import dataclass
import math
import operator
from typing import Any

import numpy as np

from .contracts import ROISelection


DEFAULT_MAX_MEASUREMENT_PIXELS = 1_048_576
DEFAULT_MIN_BACKGROUND_PIXELS = 8
_GAUSSIAN_FWHM_FACTOR = 2.0 * math.sqrt(2.0 * math.log(2.0))
_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True, slots=True)
class ROIStatistics:
    """Finite-pixel statistics for one clipped rectangular image ROI."""

    roi: ROISelection
    pixel_count: int
    finite_pixel_count: int
    invalid_pixel_count: int
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    standard_deviation: float | None = None
    sum_value: float | None = None


@dataclass(frozen=True, slots=True)
class ApertureMeasurement:
    """Background-subtracted circular-aperture measurement.

    Coordinates are zero-based image pixel centers.  ``centroid_x`` and
    ``centroid_y`` are absolute image coordinates, not cutout-relative values.
    Undefined derived quantities (for example SNR with zero measured noise)
    are represented by ``None`` rather than NaN or infinity.
    """

    center_x: float
    center_y: float
    aperture_radius: float
    background_inner_radius: float
    background_outer_radius: float
    aperture_pixel_count: int
    aperture_finite_pixel_count: int
    background_pixel_count: int
    background_finite_pixel_count: int
    invalid_pixel_count: int
    aperture_sum: float
    background_per_pixel: float
    background_rms: float
    background_total: float
    net_flux: float
    flux_uncertainty: float | None
    snr: float | None
    centroid_x: float | None
    centroid_y: float | None
    fwhm: float | None
    peak_above_background: float | None


@dataclass(frozen=True, slots=True)
class _FiniteSummary:
    minimum: float
    maximum: float
    mean: float
    median: float
    standard_deviation: float
    sum_value: float | None


class MeasurementService:
    """Bounded, NaN-safe image statistics and aperture photometry service.

    Image coordinates follow the rest of AstroView: ``x`` addresses columns,
    ``y`` addresses rows, and ROI right/bottom edges are exclusive.  Work is
    limited by the sampled cutout area rather than the full image size.
    """

    def __init__(
        self,
        *,
        max_sample_pixels: int = DEFAULT_MAX_MEASUREMENT_PIXELS,
        min_background_pixels: int = DEFAULT_MIN_BACKGROUND_PIXELS,
    ) -> None:
        self.max_sample_pixels = _positive_integer("max_sample_pixels", max_sample_pixels)
        self.min_background_pixels = _positive_integer(
            "min_background_pixels", min_background_pixels
        )

    def measure_roi(self, data: np.ndarray, roi: ROISelection) -> ROIStatistics:
        """Return finite-pixel statistics for a rectangular ROI.

        The ROI is clipped exactly as the existing SEP path clips selections.
        NaN and infinite pixels contribute only to ``invalid_pixel_count``.  If
        no finite pixels remain, numeric result fields are ``None``.
        """

        image = _real_image_2d(data)
        clipped = _clip_roi(roi, image.shape)
        self._enforce_sample_budget(clipped.width * clipped.height, "ROI")

        sample = image[
            clipped.y0 : clipped.y0 + clipped.height,
            clipped.x0 : clipped.x0 + clipped.width,
        ]
        finite_mask = np.isfinite(sample)
        finite_count = int(np.count_nonzero(finite_mask))
        pixel_count = int(sample.size)
        if finite_count == 0:
            return ROIStatistics(
                roi=clipped,
                pixel_count=pixel_count,
                finite_pixel_count=0,
                invalid_pixel_count=pixel_count,
            )

        values = np.asarray(sample[finite_mask], dtype=np.float64)
        summary = _summarize_finite(values)
        return ROIStatistics(
            roi=clipped,
            pixel_count=pixel_count,
            finite_pixel_count=finite_count,
            invalid_pixel_count=pixel_count - finite_count,
            minimum=summary.minimum,
            maximum=summary.maximum,
            mean=summary.mean,
            median=summary.median,
            standard_deviation=summary.standard_deviation,
            sum_value=summary.sum_value,
        )

    def measure_aperture(
        self,
        data: np.ndarray,
        *,
        center_x: float,
        center_y: float,
        aperture_radius: float,
        background_inner_radius: float,
        background_outer_radius: float,
    ) -> ApertureMeasurement:
        """Measure a source with a circular aperture and background annulus.

        The local background is the annulus median.  Its RMS uses the robust
        median absolute deviation, falling back to population standard
        deviation when the MAD is zero.  SNR is background-limited and includes
        the uncertainty of estimating the background from a finite annulus::

            uncertainty = rms * sqrt(N_ap + N_ap**2 / N_bg)

        Centroid and FWHM use positive, background-subtracted aperture weights.
        """

        image = _real_image_2d(data)
        height, width = image.shape
        x = _finite_number("center_x", center_x)
        y = _finite_number("center_y", center_y)
        radius = _positive_finite_number("aperture_radius", aperture_radius)
        inner = _positive_finite_number(
            "background_inner_radius", background_inner_radius
        )
        outer = _positive_finite_number(
            "background_outer_radius", background_outer_radius
        )
        if not (radius < inner < outer):
            raise ValueError(
                "Radii must satisfy aperture_radius < background_inner_radius "
                "< background_outer_radius."
            )
        if width <= 0 or height <= 0:
            raise ValueError("Measurement image is empty.")
        if not (0.0 <= x <= width - 1 and 0.0 <= y <= height - 1):
            raise ValueError(
                f"Aperture center ({x:g}, {y:g}) is outside the image bounds "
                f"0..{width - 1}, 0..{height - 1}."
            )

        x0 = int(math.floor(max(0.0, x - outer)))
        y0 = int(math.floor(max(0.0, y - outer)))
        x1 = int(math.ceil(min(float(width - 1), x + outer)))
        y1 = int(math.ceil(min(float(height - 1), y + outer)))
        cutout_width = x1 - x0 + 1
        cutout_height = y1 - y0 + 1
        self._enforce_sample_budget(cutout_width * cutout_height, "aperture cutout")

        cutout = np.asarray(image[y0 : y1 + 1, x0 : x1 + 1], dtype=np.float64)
        x_coordinates = np.arange(x0, x1 + 1, dtype=np.float64)[None, :]
        y_coordinates = np.arange(y0, y1 + 1, dtype=np.float64)[:, None]
        distance_squared = (x_coordinates - x) ** 2 + (y_coordinates - y) ** 2
        aperture_mask = distance_squared <= radius * radius
        background_mask = (
            (distance_squared >= inner * inner)
            & (distance_squared <= outer * outer)
        )
        finite_mask = np.isfinite(cutout)
        aperture_valid = aperture_mask & finite_mask
        background_valid = background_mask & finite_mask

        aperture_pixel_count = int(np.count_nonzero(aperture_mask))
        background_pixel_count = int(np.count_nonzero(background_mask))
        aperture_finite_count = int(np.count_nonzero(aperture_valid))
        background_finite_count = int(np.count_nonzero(background_valid))
        if aperture_finite_count == 0:
            raise ValueError("Circular aperture contains no finite pixels.")
        if background_finite_count < self.min_background_pixels:
            raise ValueError(
                "Background annulus contains only "
                f"{background_finite_count} finite pixels; at least "
                f"{self.min_background_pixels} are required."
            )

        aperture_values = cutout[aperture_valid]
        background_values = cutout[background_valid]
        background_summary = _summarize_finite(background_values)
        background = background_summary.median
        background_rms = _robust_rms(background_values, background)
        aperture_sum = _required_finite(
            _scaled_sum(aperture_values), "aperture sum"
        )
        background_total = _required_finite(
            background * aperture_finite_count, "aperture background"
        )
        net_flux = _required_finite(
            _sum_with_offset(aperture_values, -background), "net aperture flux"
        )

        noise_factor = math.sqrt(
            aperture_finite_count
            + (aperture_finite_count * aperture_finite_count) / background_finite_count
        )
        uncertainty = _optional_finite(background_rms * noise_factor)
        snr = None
        if uncertainty is not None and uncertainty > 0.0:
            snr = _optional_finite(net_flux / uncertainty)

        centroid_x, centroid_y, fwhm, peak = _weighted_shape_metrics(
            aperture_values,
            background,
            aperture_valid,
            x0=x0,
            y0=y0,
        )
        return ApertureMeasurement(
            center_x=x,
            center_y=y,
            aperture_radius=radius,
            background_inner_radius=inner,
            background_outer_radius=outer,
            aperture_pixel_count=aperture_pixel_count,
            aperture_finite_pixel_count=aperture_finite_count,
            background_pixel_count=background_pixel_count,
            background_finite_pixel_count=background_finite_count,
            invalid_pixel_count=(aperture_pixel_count - aperture_finite_count)
            + (background_pixel_count - background_finite_count),
            aperture_sum=aperture_sum,
            background_per_pixel=background,
            background_rms=background_rms,
            background_total=background_total,
            net_flux=net_flux,
            flux_uncertainty=uncertainty,
            snr=snr,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
            fwhm=fwhm,
            peak_above_background=peak,
        )

    def _enforce_sample_budget(self, pixel_count: int, label: str) -> None:
        if pixel_count > self.max_sample_pixels:
            raise ValueError(
                f"{label} requires {pixel_count:,} sampled pixels, exceeding the "
                f"measurement safety limit of {self.max_sample_pixels:,}."
            )


def _positive_integer(name: str, value: Any) -> int:
    # ``np.bool_`` implements ``__index__`` on some NumPy versions.  Treat it
    # like Python's ``bool`` explicitly so a safety limit cannot silently turn
    # into one sampled pixel.
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a positive integer.")
    try:
        normalized = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if normalized <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return normalized


def _finite_number(name: str, value: Any) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite number.")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be a finite number.")
    return normalized


def _positive_finite_number(name: str, value: Any) -> float:
    normalized = _finite_number(name, value)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be positive.")
    return normalized


def _real_image_2d(data: np.ndarray) -> np.ndarray:
    image = np.asarray(data)
    if image.ndim != 2:
        raise ValueError(f"Measurement requires a 2D image, got shape {image.shape}.")
    if not (
        np.issubdtype(image.dtype, np.integer)
        or np.issubdtype(image.dtype, np.floating)
        or np.issubdtype(image.dtype, np.bool_)
    ):
        raise ValueError(f"Measurement requires real numeric pixels, got dtype {image.dtype}.")
    return image


def _clip_roi(roi: ROISelection, shape: tuple[int, int]) -> ROISelection:
    try:
        x0_value = roi.x0
        y0_value = roi.y0
        width_value = roi.width
        height_value = roi.height
    except AttributeError as exc:
        raise ValueError("roi must provide x0, y0, width, and height.") from exc
    x0 = _roi_integer("roi.x0", x0_value)
    y0 = _roi_integer("roi.y0", y0_value)
    width = _roi_integer("roi.width", width_value)
    height = _roi_integer("roi.height", height_value)
    if width <= 0 or height <= 0:
        raise ValueError("ROI width and height must be positive.")

    image_height, image_width = shape
    clipped_x0 = max(0, min(x0, image_width))
    clipped_y0 = max(0, min(y0, image_height))
    clipped_x1 = max(clipped_x0, min(x0 + width, image_width))
    clipped_y1 = max(clipped_y0, min(y0 + height, image_height))
    if clipped_x1 <= clipped_x0 or clipped_y1 <= clipped_y0:
        raise ValueError("Selected ROI is empty after clipping to the image.")
    return ROISelection(
        x0=clipped_x0,
        y0=clipped_y0,
        width=clipped_x1 - clipped_x0,
        height=clipped_y1 - clipped_y0,
    )


def _roi_integer(name: str, value: Any) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be an integer.")
    try:
        return operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _summarize_finite(values: np.ndarray) -> _FiniteSummary:
    scale = float(np.max(np.abs(values)))
    if scale == 0.0:
        return _FiniteSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    scaled = values / scale
    mean_scaled = float(np.mean(scaled, dtype=np.float64))
    median_scaled = float(np.median(scaled))
    centered = scaled - mean_scaled
    standard_deviation = _required_finite(
        float(np.sqrt(np.mean(centered * centered, dtype=np.float64))) * scale,
        "standard deviation",
    )
    return _FiniteSummary(
        minimum=float(np.min(values)),
        maximum=float(np.max(values)),
        mean=_required_finite(mean_scaled * scale, "mean"),
        median=_required_finite(median_scaled * scale, "median"),
        standard_deviation=standard_deviation,
        sum_value=_optional_finite(float(np.sum(scaled, dtype=np.float64)) * scale),
    )


def _scaled_sum(values: np.ndarray) -> float:
    scale = float(np.max(np.abs(values)))
    if scale == 0.0:
        return 0.0
    return float(np.sum(values / scale, dtype=np.float64)) * scale


def _sum_with_offset(values: np.ndarray, offset: float) -> float:
    scale = max(float(np.max(np.abs(values))), abs(offset))
    if scale == 0.0:
        return 0.0
    scaled_total = np.sum((values / scale) + (offset / scale), dtype=np.float64)
    return float(scaled_total) * scale


def _robust_rms(values: np.ndarray, median: float) -> float:
    scale = max(float(np.max(np.abs(values))), abs(median))
    if scale == 0.0:
        return 0.0
    scaled = values / scale
    median_scaled = median / scale
    mad_scaled = float(np.median(np.abs(scaled - median_scaled)))
    robust = _optional_finite(mad_scaled * scale * _MAD_TO_SIGMA)
    if robust is not None and robust > 0.0:
        return robust
    return _summarize_finite(values).standard_deviation


def _weighted_shape_metrics(
    aperture_values: np.ndarray,
    background: float,
    aperture_valid: np.ndarray,
    *,
    x0: int,
    y0: int,
) -> tuple[float | None, float | None, float | None, float | None]:
    scale = max(float(np.max(np.abs(aperture_values))), abs(background))
    if scale == 0.0:
        return None, None, None, None

    residual_scaled = (aperture_values / scale) - (background / scale)
    peak = _optional_finite(float(np.max(residual_scaled)) * scale)
    weights = np.clip(residual_scaled, 0.0, None)
    weight_sum = float(np.sum(weights, dtype=np.float64))
    if not math.isfinite(weight_sum) or weight_sum <= 0.0:
        return None, None, None, peak

    rows, columns = np.nonzero(aperture_valid)
    x_values = columns.astype(np.float64, copy=False) + x0
    y_values = rows.astype(np.float64, copy=False) + y0
    centroid_x = _optional_finite(float(np.dot(weights, x_values) / weight_sum))
    centroid_y = _optional_finite(float(np.dot(weights, y_values) / weight_sum))
    if centroid_x is None or centroid_y is None:
        return None, None, None, peak

    radial_variance = float(
        np.dot(
            weights,
            (x_values - centroid_x) ** 2 + (y_values - centroid_y) ** 2,
        )
        / weight_sum
    )
    if not math.isfinite(radial_variance) or radial_variance < 0.0:
        fwhm = None
    else:
        fwhm = _optional_finite(
            _GAUSSIAN_FWHM_FACTOR * math.sqrt(radial_variance / 2.0)
        )
    return centroid_x, centroid_y, fwhm, peak


def _required_finite(value: float, label: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{label.capitalize()} exceeds the finite numeric range.")
    return normalized


def _optional_finite(value: float) -> float | None:
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


__all__ = [
    "ApertureMeasurement",
    "DEFAULT_MAX_MEASUREMENT_PIXELS",
    "DEFAULT_MIN_BACKGROUND_PIXELS",
    "MeasurementService",
    "ROIStatistics",
]
