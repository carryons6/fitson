from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.fits_data import FITSData
from ..core.fits_service import compute_interval_limits, render_image_u8
from ..core.image_comparison import ImageComparisonResult, compare_fits_images


MAX_COMPARISON_UI_PIXELS = 4_096**2
MAX_SHARED_INTERVAL_SAMPLES = 1_000_000


@dataclass(slots=True)
class ComparisonDisplayResult:
    result: ImageComparisonResult
    left_u8: np.ndarray | None = None
    right_u8: np.ndarray | None = None
    difference_u8: np.ndarray | None = None


def _bounded_finite_sample(array: np.ndarray, target: int) -> np.ndarray:
    height, width = array.shape[:2]
    if array.size <= target:
        sample = array.reshape(-1)
    else:
        step = max(1, int(np.ceil(np.sqrt(array.size / float(target)))))
        sample = array[::step, ::step].reshape(-1)
    finite = np.isfinite(sample)
    return np.asarray(sample[finite], dtype=np.float64)


def _shared_limits(
    left: np.ndarray,
    right: np.ndarray,
    interval_name: str,
    manual_limits: tuple[float, float] | None,
) -> tuple[float, float] | None:
    if interval_name == "Manual" and manual_limits is not None:
        return manual_limits
    per_image = max(1, MAX_SHARED_INTERVAL_SAMPLES // 2)
    left_sample = _bounded_finite_sample(left, per_image)
    right_sample = _bounded_finite_sample(right, per_image)
    if left_sample.size == 0 and right_sample.size == 0:
        return None
    combined = np.concatenate((left_sample, right_sample))
    return compute_interval_limits(
        FITSData(data=combined.reshape(1, -1)),
        interval_name,
    )


class ComparisonWorker(QObject):
    """Run bounded comparison and display rendering away from the GUI thread."""

    finished = Signal()
    result_ready = Signal(object)
    comparison_error = Signal(str)

    def __init__(
        self,
        left: FITSData,
        right: FITSData,
        *,
        mode: str,
        alignment: str,
        stretch_name: str,
        interval_name: str,
        manual_limits: tuple[float, float] | None,
    ) -> None:
        super().__init__()
        self.left = left
        self.right = right
        self.mode = mode
        self.alignment = alignment
        self.stretch_name = stretch_name
        self.interval_name = interval_name
        self.manual_limits = manual_limits
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled or QThread.currentThread().isInterruptionRequested()

    @Slot()
    def run(self) -> None:
        try:
            if self._is_cancelled():
                return
            result = compare_fits_images(
                self.left,
                self.right,
                mode=self.mode,
                alignment=self.alignment,
                max_output_pixels=MAX_COMPARISON_UI_PIXELS,
                max_wcs_pixels=MAX_COMPARISON_UI_PIXELS,
            )
            display = ComparisonDisplayResult(result=result)
            if not result.success or self._is_cancelled():
                if not self._is_cancelled():
                    self.result_ready.emit(display)
                return

            if result.difference_image is not None:
                display.difference_u8 = render_image_u8(
                    FITSData(data=result.difference_image),
                    self.stretch_name,
                    self.interval_name,
                    manual_limits=self.manual_limits,
                )
            elif result.left_image is not None and result.right_image is not None:
                limits = _shared_limits(
                    result.left_image,
                    result.right_image,
                    self.interval_name,
                    self.manual_limits,
                )
                interval = "Manual" if limits is not None else self.interval_name
                display.left_u8 = render_image_u8(
                    FITSData(data=result.left_image),
                    self.stretch_name,
                    interval,
                    manual_limits=limits,
                )
                if self._is_cancelled():
                    return
                display.right_u8 = render_image_u8(
                    FITSData(data=result.right_image),
                    self.stretch_name,
                    interval,
                    manual_limits=limits,
                )
            if not self._is_cancelled():
                self.result_ready.emit(display)
        except Exception as exc:
            if not self._is_cancelled():
                self.comparison_error.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = ["ComparisonDisplayResult", "ComparisonWorker", "MAX_COMPARISON_UI_PIXELS"]
