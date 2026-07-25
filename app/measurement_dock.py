from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.measurement_service import ApertureMeasurement, ROIStatistics


class MeasurementDock(QDockWidget):
    """Independent UI for ROI statistics and aperture-photometry results.

    Integration contract:

    - call :meth:`set_image_shape` when the active frame changes;
    - pass ROI results to :meth:`set_roi_statistics`;
    - connect :attr:`aperture_measurement_requested` and call
      ``MeasurementService.measure_aperture`` with the five emitted values;
    - pass the result to :meth:`set_aperture_measurement`.
    """

    aperture_measurement_requested = Signal(float, float, float, float, float)
    clear_requested = Signal()

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("measurement_dock")
        self.setWindowTitle(self.tr("Measurement Workbench"))
        self._has_image = False
        self._busy = False

        content = QWidget(self)
        layout = QVBoxLayout(content)

        roi_group = QGroupBox(self.tr("ROI Pixel Statistics"), content)
        roi_form = QFormLayout(roi_group)
        self.roi_value_labels = {
            "region": QLabel("—", roi_group),
            "pixels": QLabel("—", roi_group),
            "finite_invalid": QLabel("—", roi_group),
            "minimum_maximum": QLabel("—", roi_group),
            "mean_median": QLabel("—", roi_group),
            "standard_deviation": QLabel("—", roi_group),
            "sum": QLabel("—", roi_group),
        }
        roi_form.addRow(self.tr("Region:"), self.roi_value_labels["region"])
        roi_form.addRow(self.tr("Pixels:"), self.roi_value_labels["pixels"])
        roi_form.addRow(
            self.tr("Finite / Invalid:"), self.roi_value_labels["finite_invalid"]
        )
        roi_form.addRow(
            self.tr("Minimum / Maximum:"), self.roi_value_labels["minimum_maximum"]
        )
        roi_form.addRow(self.tr("Mean / Median:"), self.roi_value_labels["mean_median"])
        roi_form.addRow(
            self.tr("Standard deviation:"),
            self.roi_value_labels["standard_deviation"],
        )
        roi_form.addRow(self.tr("Sum:"), self.roi_value_labels["sum"])
        layout.addWidget(roi_group)

        aperture_group = QGroupBox(self.tr("Circular Aperture"), content)
        aperture_form = QFormLayout(aperture_group)
        self.center_x_spin = _coordinate_spin(aperture_group)
        self.center_y_spin = _coordinate_spin(aperture_group)
        self.aperture_radius_spin = _radius_spin(aperture_group, 5.0)
        self.background_inner_radius_spin = _radius_spin(aperture_group, 8.0)
        self.background_outer_radius_spin = _radius_spin(aperture_group, 12.0)
        aperture_form.addRow(self.tr("Center X:"), self.center_x_spin)
        aperture_form.addRow(self.tr("Center Y:"), self.center_y_spin)
        aperture_form.addRow(self.tr("Aperture radius:"), self.aperture_radius_spin)
        aperture_form.addRow(
            self.tr("Background inner radius:"),
            self.background_inner_radius_spin,
        )
        aperture_form.addRow(
            self.tr("Background outer radius:"),
            self.background_outer_radius_spin,
        )

        aperture_buttons = QWidget(aperture_group)
        aperture_button_layout = QHBoxLayout(aperture_buttons)
        aperture_button_layout.setContentsMargins(0, 0, 0, 0)
        self.measure_button = QPushButton(self.tr("Measure Aperture"), aperture_buttons)
        self.clear_button = QPushButton(self.tr("Clear Results"), aperture_buttons)
        aperture_button_layout.addWidget(self.measure_button)
        aperture_button_layout.addWidget(self.clear_button)
        aperture_form.addRow(aperture_buttons)
        layout.addWidget(aperture_group)

        result_group = QGroupBox(self.tr("Photometry and Shape"), content)
        result_form = QFormLayout(result_group)
        self.aperture_value_labels = {
            "net_flux": QLabel("—", result_group),
            "aperture_sum": QLabel("—", result_group),
            "background": QLabel("—", result_group),
            "background_rms": QLabel("—", result_group),
            "uncertainty": QLabel("—", result_group),
            "snr": QLabel("—", result_group),
            "centroid": QLabel("—", result_group),
            "fwhm": QLabel("—", result_group),
            "peak": QLabel("—", result_group),
            "pixels": QLabel("—", result_group),
        }
        result_form.addRow(self.tr("Net flux:"), self.aperture_value_labels["net_flux"])
        result_form.addRow(
            self.tr("Aperture sum:"), self.aperture_value_labels["aperture_sum"]
        )
        result_form.addRow(
            self.tr("Background / pixel:"), self.aperture_value_labels["background"]
        )
        result_form.addRow(
            self.tr("Background RMS:"), self.aperture_value_labels["background_rms"]
        )
        result_form.addRow(
            self.tr("Flux uncertainty:"), self.aperture_value_labels["uncertainty"]
        )
        result_form.addRow(self.tr("SNR:"), self.aperture_value_labels["snr"])
        result_form.addRow(self.tr("Centroid (x, y):"), self.aperture_value_labels["centroid"])
        result_form.addRow(self.tr("FWHM:"), self.aperture_value_labels["fwhm"])
        result_form.addRow(
            self.tr("Peak above background:"), self.aperture_value_labels["peak"]
        )
        result_form.addRow(
            self.tr("Aperture / Background pixels:"),
            self.aperture_value_labels["pixels"],
        )
        layout.addWidget(result_group)

        self.status_label = QLabel(self.tr("Load an image to begin measuring."), content)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.setWidget(content)

        self.measure_button.clicked.connect(self._emit_aperture_request)
        self.clear_button.clicked.connect(self._clear_from_button)
        self._sync_measure_button()

    def set_image_shape(self, width: int | None, height: int | None) -> None:
        """Set active image bounds, or pass ``None`` to disable measurement."""

        if width is None or height is None or int(width) <= 0 or int(height) <= 0:
            self._has_image = False
            # A pending result belongs to the image that was just detached.
            # Resetting busy here prevents a later image from inheriting a
            # permanently disabled Measure button.
            self._busy = False
            self.center_x_spin.setMaximum(0.0)
            self.center_y_spin.setMaximum(0.0)
            self.clear_results()
            self.status_label.setText(self.tr("Load an image to begin measuring."))
            self._sync_measure_button()
            return

        image_width = int(width)
        image_height = int(height)
        self._has_image = True
        self.center_x_spin.setMaximum(float(image_width - 1))
        self.center_y_spin.setMaximum(float(image_height - 1))
        self.status_label.setText(
            self.tr("Ready — image {width} × {height} pixels.").format(
                width=image_width,
                height=image_height,
            )
        )
        self._sync_measure_button()

    def set_center(self, x: float, y: float) -> None:
        """Populate the aperture center, for example from a canvas click."""

        self.center_x_spin.setValue(float(x))
        self.center_y_spin.setValue(float(y))

    def aperture_parameters(self) -> dict[str, float]:
        """Return keyword arguments accepted by ``measure_aperture``."""

        return {
            "center_x": self.center_x_spin.value(),
            "center_y": self.center_y_spin.value(),
            "aperture_radius": self.aperture_radius_spin.value(),
            "background_inner_radius": self.background_inner_radius_spin.value(),
            "background_outer_radius": self.background_outer_radius_spin.value(),
        }

    def set_roi_statistics(self, result: ROIStatistics | None) -> None:
        """Render an ROI statistics result, or clear that result section."""

        if result is None:
            for label in self.roi_value_labels.values():
                label.setText("—")
            return

        roi = result.roi
        self.roi_value_labels["region"].setText(
            f"x={roi.x0}, y={roi.y0}, {roi.width} × {roi.height}"
        )
        self.roi_value_labels["pixels"].setText(f"{result.pixel_count:,}")
        self.roi_value_labels["finite_invalid"].setText(
            f"{result.finite_pixel_count:,} / {result.invalid_pixel_count:,}"
        )
        self.roi_value_labels["minimum_maximum"].setText(
            f"{_format_value(result.minimum)} / {_format_value(result.maximum)}"
        )
        self.roi_value_labels["mean_median"].setText(
            f"{_format_value(result.mean)} / {_format_value(result.median)}"
        )
        self.roi_value_labels["standard_deviation"].setText(
            _format_value(result.standard_deviation)
        )
        self.roi_value_labels["sum"].setText(_format_value(result.sum_value))
        if result.finite_pixel_count:
            self.status_label.setText(self.tr("ROI statistics updated."))
        else:
            self.status_label.setText(self.tr("ROI contains no finite pixels."))

    def set_aperture_measurement(self, result: ApertureMeasurement | None) -> None:
        """Render an aperture measurement, or clear that result section."""

        if result is None:
            for label in self.aperture_value_labels.values():
                label.setText("—")
            return

        # Receiving a result is the terminal state of a measurement request.
        # Consumers may still call set_busy(False) explicitly; doing it here
        # keeps the dock correct for both synchronous and worker-based wiring.
        self._busy = False

        self.aperture_value_labels["net_flux"].setText(_format_value(result.net_flux))
        self.aperture_value_labels["aperture_sum"].setText(
            _format_value(result.aperture_sum)
        )
        self.aperture_value_labels["background"].setText(
            _format_value(result.background_per_pixel)
        )
        self.aperture_value_labels["background_rms"].setText(
            _format_value(result.background_rms)
        )
        self.aperture_value_labels["uncertainty"].setText(
            _format_value(result.flux_uncertainty)
        )
        self.aperture_value_labels["snr"].setText(_format_value(result.snr))
        self.aperture_value_labels["centroid"].setText(
            f"{_format_value(result.centroid_x)}, {_format_value(result.centroid_y)}"
        )
        self.aperture_value_labels["fwhm"].setText(_format_value(result.fwhm))
        self.aperture_value_labels["peak"].setText(
            _format_value(result.peak_above_background)
        )
        self.aperture_value_labels["pixels"].setText(
            f"{result.aperture_finite_pixel_count:,} / "
            f"{result.background_finite_pixel_count:,}"
        )
        self.status_label.setText(self.tr("Aperture measurement updated."))
        self._sync_measure_button()

    def set_busy(self, busy: bool) -> None:
        """Mark an externally scheduled measurement as running or complete."""

        self._busy = bool(busy)
        if self._busy:
            self.status_label.setText(self.tr("Measuring..."))
        self._sync_measure_button()

    def set_error(self, detail: str) -> None:
        """Display a non-modal measurement error supplied by the integrator."""

        self._busy = False
        self.status_label.setText(
            self.tr("Measurement failed: {detail}").format(detail=str(detail))
        )
        self._sync_measure_button()

    def clear_results(self) -> None:
        """Clear both result sections without changing aperture parameters."""

        self.set_roi_statistics(None)
        self.set_aperture_measurement(None)

    def _emit_aperture_request(self) -> None:
        params = self.aperture_parameters()
        self.aperture_measurement_requested.emit(
            params["center_x"],
            params["center_y"],
            params["aperture_radius"],
            params["background_inner_radius"],
            params["background_outer_radius"],
        )

    def _clear_from_button(self) -> None:
        self.clear_results()
        self.status_label.setText(self.tr("Measurement results cleared."))
        self.clear_requested.emit()

    def _sync_measure_button(self) -> None:
        self.measure_button.setEnabled(self._has_image and not self._busy)


def _coordinate_spin(parent: QWidget) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setDecimals(3)
    spin.setRange(0.0, 0.0)
    spin.setSingleStep(1.0)
    spin.setKeyboardTracking(False)
    spin.setSuffix(" px")
    return spin


def _radius_spin(parent: QWidget, value: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setDecimals(2)
    spin.setRange(0.1, 8192.0)
    spin.setValue(value)
    spin.setSingleStep(0.5)
    spin.setKeyboardTracking(False)
    spin.setSuffix(" px")
    return spin


def _format_value(value: float | None) -> str:
    if value is None:
        return "—"
    normalized = float(value)
    if not math.isfinite(normalized):
        return "—"
    return f"{normalized:.8g}"


__all__ = ["MeasurementDock"]
