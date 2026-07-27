from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.contracts import ROISelection
from ..core.moving_targets import MovingTargetParameters, MovingTargetResult
from .i18n import localize_moving_target_text


class MovingTargetDock(QDockWidget):
    """Controls and result table for multi-frame moving-target detection."""

    roi_capture_requested = Signal()
    use_full_frame_requested = Signal()
    detection_requested = Signal(object, float, bool)
    cancel_requested = Signal()
    clear_requested = Signal()
    export_requested = Signal()
    target_selected = Signal(int)

    _COLUMNS = ("ID", "Hits", "X", "Y", "VX", "VY", "Speed", "RMS")

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(self.tr("Moving Targets"), parent)
        self.setObjectName("moving_target_dock")
        self._frame_count = 0
        self._frame_shape: tuple[int, int] | None = None
        self._roi: ROISelection | None = None
        self._result: MovingTargetResult | None = None
        self._current_frame = 0
        self._busy = False

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.input_label = QLabel(self.tr("Load at least 5 equal-sized frames."), body)
        self.input_label.setWordWrap(True)
        self.input_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.input_label)

        self.roi_label = QLabel(self.tr("Analysis area: full frame"), body)
        self.roi_label.setWordWrap(True)
        self.roi_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.roi_label)

        roi_buttons = QHBoxLayout()
        self.select_roi_button = QPushButton(self.tr("Select ROI"), body)
        self.select_roi_button.setObjectName("moving_select_roi_button")
        self.full_frame_button = QPushButton(self.tr("Use Full Frame"), body)
        self.full_frame_button.setObjectName("moving_full_frame_button")
        roi_buttons.addWidget(self.select_roi_button)
        roi_buttons.addWidget(self.full_frame_button)
        layout.addLayout(roi_buttons)

        form = QFormLayout()
        self.threshold_spin = QDoubleSpinBox(body)
        self.threshold_spin.setObjectName("moving_threshold_spin")
        self.threshold_spin.setRange(2.0, 20.0)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setValue(5.0)
        self.threshold_spin.setSuffix(" sigma")
        form.addRow(self.tr("SEP threshold:"), self.threshold_spin)

        self.min_hits_spin = QSpinBox(body)
        self.min_hits_spin.setObjectName("moving_min_hits_spin")
        self.min_hits_spin.setRange(0, 4096)
        self.min_hits_spin.setSpecialValueText(self.tr("Auto"))
        self.min_hits_spin.setValue(0)
        form.addRow(self.tr("Minimum hits:"), self.min_hits_spin)

        self.min_speed_spin = QDoubleSpinBox(body)
        self.min_speed_spin.setObjectName("moving_min_speed_spin")
        self.min_speed_spin.setRange(0.0, 10_000.0)
        self.min_speed_spin.setDecimals(3)
        self.min_speed_spin.setValue(2.0)
        self.min_speed_spin.setSuffix(" px/s")
        form.addRow(self.tr("Minimum speed:"), self.min_speed_spin)

        self.max_speed_spin = QDoubleSpinBox(body)
        self.max_speed_spin.setObjectName("moving_max_speed_spin")
        self.max_speed_spin.setRange(0.001, 10_000.0)
        self.max_speed_spin.setDecimals(3)
        self.max_speed_spin.setValue(60.0)
        self.max_speed_spin.setSuffix(" px/s")
        form.addRow(self.tr("Maximum speed:"), self.max_speed_spin)

        self.max_rms_spin = QDoubleSpinBox(body)
        self.max_rms_spin.setObjectName("moving_max_rms_spin")
        self.max_rms_spin.setRange(0.01, 20.0)
        self.max_rms_spin.setDecimals(2)
        self.max_rms_spin.setValue(0.4)
        self.max_rms_spin.setSuffix(" px")
        form.addRow(self.tr("Maximum track RMS:"), self.max_rms_spin)

        self.prefer_header_times_check = QCheckBox(self.tr("Prefer FITS timestamps"), body)
        self.prefer_header_times_check.setObjectName("moving_prefer_header_times_check")
        self.prefer_header_times_check.setChecked(True)
        form.addRow(self.prefer_header_times_check)

        self.cadence_spin = QDoubleSpinBox(body)
        self.cadence_spin.setObjectName("moving_cadence_spin")
        self.cadence_spin.setRange(0.001, 86_400.0)
        self.cadence_spin.setDecimals(3)
        self.cadence_spin.setValue(1.0)
        self.cadence_spin.setSuffix(" s")
        form.addRow(self.tr("Fallback cadence:"), self.cadence_spin)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        self.detect_button = QPushButton(self.tr("Detect"), body)
        self.detect_button.setObjectName("moving_detect_button")
        self.cancel_button = QPushButton(self.tr("Cancel"), body)
        self.cancel_button.setObjectName("moving_cancel_button")
        self.clear_button = QPushButton(self.tr("Clear"), body)
        self.clear_button.setObjectName("moving_clear_button")
        action_row.addWidget(self.detect_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.clear_button)
        layout.addLayout(action_row)

        self.status_label = QLabel(self.tr("Ready."), body)
        self.status_label.setObjectName("moving_status_label")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)

        self.result_table = QTableWidget(0, len(self._COLUMNS), body)
        self.result_table.setObjectName("moving_result_table")
        self.result_table.setHorizontalHeaderLabels([self.tr(name) for name in self._COLUMNS])
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.result_table, 1)

        self.export_button = QPushButton(self.tr("Export CSV..."), body)
        self.export_button.setObjectName("moving_export_button")
        layout.addWidget(self.export_button)
        self.setWidget(body)

        self.select_roi_button.clicked.connect(self.roi_capture_requested.emit)
        self.full_frame_button.clicked.connect(self.use_full_frame_requested.emit)
        self.detect_button.clicked.connect(self._request_detection)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        self.export_button.clicked.connect(self.export_requested.emit)
        self.result_table.itemSelectionChanged.connect(self._emit_selection)
        self._refresh_controls()

    def parameters(self) -> MovingTargetParameters:
        return MovingTargetParameters(
            detection_threshold=self.threshold_spin.value(),
            min_track_hits=self.min_hits_spin.value(),
            min_track_speed=self.min_speed_spin.value(),
            max_track_speed=self.max_speed_spin.value(),
            max_track_rms=self.max_rms_spin.value(),
        )

    def set_input_context(
        self,
        frame_count: int,
        frame_shape: tuple[int, int] | None,
        roi: ROISelection | None,
    ) -> None:
        self._frame_count = max(0, int(frame_count))
        self._frame_shape = frame_shape
        self._roi = roi
        if frame_shape is None:
            self.input_label.setText(self.tr("Load at least 5 equal-sized frames."))
        else:
            width, height = frame_shape
            self.input_label.setText(
                self.tr("Frames: {count}; common size: {width} x {height}").format(
                    count=self._frame_count,
                    width=width,
                    height=height,
                )
            )
        self._refresh_roi_label()
        self._refresh_controls()

    def set_roi(self, roi: ROISelection | None) -> None:
        self._roi = roi
        self._refresh_roi_label()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._refresh_controls()

    def set_status(self, message: str) -> None:
        self.status_label.setText(str(message))

    def set_result(self, result: MovingTargetResult, current_frame: int = 0) -> None:
        self._result = result
        self._current_frame = max(0, int(current_frame))
        self.result_table.setRowCount(len(result.tracks))
        for row, track in enumerate(result.tracks):
            values = (
                f"T{track.target_id}",
                f"{track.hits}/{result.frame_count}",
                "",
                "",
                f"{track.vx:+.4f}",
                f"{track.vy:+.4f}",
                f"{track.speed:.4f}",
                f"{track.rms:.3f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.result_table.setItem(row, column, item)
        self.update_current_frame(self._current_frame)
        warning = (
            f" {localize_moving_target_text(result.warnings[0], self.tr)}"
            if result.warnings
            else ""
        )
        self.set_status(
            self.tr("Found {count} moving target(s). Time source: {source}.").format(
                count=len(result.tracks),
                source=localize_moving_target_text(result.time_source, self.tr),
            )
            + warning
        )
        self._refresh_controls()

    def update_current_frame(self, frame_index: int) -> None:
        self._current_frame = max(0, int(frame_index))
        result = self._result
        if result is None or not 0 <= self._current_frame < result.frame_count:
            return
        for row, track in enumerate(result.tracks):
            position = track.positions[self._current_frame]
            x_item = self.result_table.item(row, 2)
            y_item = self.result_table.item(row, 3)
            if x_item is not None:
                x_item.setText(f"{float(position[0]):.2f}")
            if y_item is not None:
                y_item.setText(f"{float(position[1]):.2f}")

    def clear_results(self) -> None:
        self._result = None
        self.result_table.setRowCount(0)
        self.set_status(self.tr("No moving-target results."))
        self._refresh_controls()

    def result(self) -> MovingTargetResult | None:
        return self._result

    def _refresh_roi_label(self) -> None:
        roi = self._roi
        if roi is None:
            self.roi_label.setText(self.tr("Analysis area: full frame"))
            return
        self.roi_label.setText(
            self.tr("Analysis ROI: x=[{x0},{x1}), y=[{y0},{y1}) ({width} x {height})").format(
                x0=roi.x0,
                x1=roi.x0 + roi.width,
                y0=roi.y0,
                y1=roi.y0 + roi.height,
                width=roi.width,
                height=roi.height,
            )
        )

    def _refresh_controls(self) -> None:
        ready = self._frame_count >= 5 and self._frame_shape is not None
        self.detect_button.setEnabled(ready and not self._busy)
        self.cancel_button.setEnabled(self._busy)
        self.select_roi_button.setEnabled(self._frame_shape is not None and not self._busy)
        self.full_frame_button.setEnabled(self._frame_shape is not None and not self._busy)
        self.clear_button.setEnabled(not self._busy and self._result is not None)
        self.export_button.setEnabled(not self._busy and self._result is not None and bool(self._result.tracks))
        for widget in (
            self.threshold_spin,
            self.min_hits_spin,
            self.min_speed_spin,
            self.max_speed_spin,
            self.max_rms_spin,
            self.prefer_header_times_check,
            self.cadence_spin,
        ):
            widget.setEnabled(not self._busy)

    def _request_detection(self) -> None:
        if not self.detect_button.isEnabled():
            return
        self.detection_requested.emit(
            self.parameters(),
            self.cadence_spin.value(),
            self.prefer_header_times_check.isChecked(),
        )

    def _emit_selection(self) -> None:
        row = self.result_table.currentRow()
        if row >= 0 and self._result is not None and row < len(self._result.tracks):
            self.target_selected.emit(row)


__all__ = ["MovingTargetDock"]
