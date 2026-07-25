from __future__ import annotations

import math
import operator
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.image_comparison import (
    ComparisonAlignment,
    ComparisonMode,
    ImageComparisonResult,
)


class ComparisonDock(QDockWidget):
    """Standalone controls for two-image comparison presentation.

    The dock deliberately owns no image arrays or canvases.  Consumers select
    the two operands, call the core comparison API, and feed completion back
    through :meth:`set_comparison_result`.  View synchronization is exposed as
    relay methods/signals so a future dual-canvas host can connect zoom and pan
    events without coupling either canvas to this panel.
    """

    image_selection_requested = Signal(int)  # pane: 0 = frame A, 1 = frame B
    swap_requested = Signal()
    clear_requested = Signal()
    comparison_requested = Signal(str, str)  # mode, alignment
    mode_changed = Signal(str)
    alignment_changed = Signal(str)
    blink_active_changed = Signal(bool)
    blink_phase_changed = Signal(int)  # pane to display: 0 = frame A, 1 = frame B
    blink_interval_changed = Signal(int)
    view_sync_changed = Signal(bool)
    zoom_sync_requested = Signal(int, float, float, float)  # target, scale, cx, cy
    pan_sync_requested = Signal(int, float, float)  # target, cx, cy

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("comparison_dock")
        self.setWindowTitle(self.tr("Image Comparison"))

        self._left_name: str | None = None
        self._right_name: str | None = None
        self._busy = False
        self._comparison_available = False
        self._blink_phase = 0

        content = QWidget(self)
        layout = QVBoxLayout(content)

        inputs_group = QGroupBox(self.tr("Images"), content)
        inputs_layout = QFormLayout(inputs_group)
        self.left_label = QLabel(self.tr("Not selected"), inputs_group)
        self.left_label.setTextFormat(Qt.TextFormat.PlainText)
        self.left_label.setWordWrap(True)
        self.right_label = QLabel(self.tr("Not selected"), inputs_group)
        self.right_label.setTextFormat(Qt.TextFormat.PlainText)
        self.right_label.setWordWrap(True)
        self.select_left_button = QPushButton(self.tr("Choose frame A..."), inputs_group)
        self.select_right_button = QPushButton(self.tr("Choose frame B..."), inputs_group)

        left_row = QWidget(inputs_group)
        left_layout = QHBoxLayout(left_row)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.left_label, 1)
        left_layout.addWidget(self.select_left_button)
        right_row = QWidget(inputs_group)
        right_layout = QHBoxLayout(right_row)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.right_label, 1)
        right_layout.addWidget(self.select_right_button)
        inputs_layout.addRow(self.tr("Frame A:"), left_row)
        inputs_layout.addRow(self.tr("Frame B:"), right_row)
        layout.addWidget(inputs_group)

        options_group = QGroupBox(self.tr("Comparison"), content)
        options_layout = QFormLayout(options_group)
        self.mode_combo = QComboBox(options_group)
        self.mode_combo.addItem(self.tr("Side by side"), ComparisonMode.SIDE_BY_SIDE.value)
        self.mode_combo.addItem(self.tr("Blink"), ComparisonMode.BLINK.value)
        self.mode_combo.addItem(self.tr("Difference (A - B)"), ComparisonMode.DIFFERENCE.value)
        options_layout.addRow(self.tr("Mode:"), self.mode_combo)

        self.alignment_combo = QComboBox(options_group)
        self.alignment_combo.addItem(self.tr("Automatic"), ComparisonAlignment.AUTO.value)
        self.alignment_combo.addItem(self.tr("Direct pixels"), ComparisonAlignment.PIXEL.value)
        self.alignment_combo.addItem(self.tr("WCS (nearest neighbour)"), ComparisonAlignment.WCS.value)
        options_layout.addRow(self.tr("Alignment:"), self.alignment_combo)

        self.sync_views_check = QCheckBox(self.tr("Synchronize zoom and pan"), options_group)
        self.sync_views_check.setChecked(True)
        options_layout.addRow(self.sync_views_check)
        layout.addWidget(options_group)

        blink_group = QGroupBox(self.tr("Blink controls"), content)
        blink_layout = QFormLayout(blink_group)
        self.blink_interval_spin = QSpinBox(blink_group)
        self.blink_interval_spin.setRange(100, 5_000)
        self.blink_interval_spin.setSingleStep(100)
        self.blink_interval_spin.setValue(500)
        self.blink_interval_spin.setSuffix(self.tr(" ms"))
        blink_layout.addRow(self.tr("Interval:"), self.blink_interval_spin)
        self.blink_toggle_button = QPushButton(self.tr("Start blinking"), blink_group)
        self.blink_toggle_button.setCheckable(True)
        blink_layout.addRow(self.blink_toggle_button)
        layout.addWidget(blink_group)
        self.blink_group = blink_group

        action_row = QWidget(content)
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.compare_button = QPushButton(self.tr("Compare"), action_row)
        self.swap_button = QPushButton(self.tr("Swap"), action_row)
        self.clear_button = QPushButton(self.tr("Clear"), action_row)
        action_layout.addWidget(self.compare_button)
        action_layout.addWidget(self.swap_button)
        action_layout.addWidget(self.clear_button)
        layout.addWidget(action_row)

        self.status_label = QLabel(self.tr("Choose two images to compare."), content)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.setWidget(content)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(self.blink_interval_spin.value())
        self._blink_timer.timeout.connect(self._advance_blink)

        self.select_left_button.clicked.connect(
            lambda: self.image_selection_requested.emit(0)
        )
        self.select_right_button.clicked.connect(
            lambda: self.image_selection_requested.emit(1)
        )
        self.compare_button.clicked.connect(self._request_comparison)
        self.swap_button.clicked.connect(lambda: self.swap_requested.emit())
        self.clear_button.clicked.connect(self._request_clear)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.alignment_combo.currentIndexChanged.connect(self._on_alignment_changed)
        self.sync_views_check.toggled.connect(self.view_sync_changed.emit)
        self.blink_interval_spin.valueChanged.connect(self._on_blink_interval_changed)
        self.blink_toggle_button.toggled.connect(self._toggle_blink)
        self._refresh_controls()

    def mode(self) -> ComparisonMode:
        return ComparisonMode(str(self.mode_combo.currentData()))

    def alignment(self) -> ComparisonAlignment:
        return ComparisonAlignment(str(self.alignment_combo.currentData()))

    def blink_interval_ms(self) -> int:
        return self.blink_interval_spin.value()

    def view_sync_enabled(self) -> bool:
        return self.sync_views_check.isChecked()

    def set_view_sync_enabled(self, enabled: bool) -> None:
        self.sync_views_check.setChecked(bool(enabled))

    def set_mode(self, mode: ComparisonMode | str) -> None:
        value = mode.value if isinstance(mode, ComparisonMode) else str(mode)
        index = self.mode_combo.findData(value)
        if index < 0:
            raise ValueError(f"Unsupported comparison mode: {mode!r}")
        self.mode_combo.setCurrentIndex(index)

    def set_alignment(self, alignment: ComparisonAlignment | str) -> None:
        value = alignment.value if isinstance(alignment, ComparisonAlignment) else str(alignment)
        index = self.alignment_combo.findData(value)
        if index < 0:
            raise ValueError(f"Unsupported comparison alignment: {alignment!r}")
        self.alignment_combo.setCurrentIndex(index)

    def set_blink_interval_ms(self, interval_ms: int) -> None:
        """Set the blink cadence, bounded by the visible spin-box limits."""

        if isinstance(interval_ms, bool):
            raise ValueError("Blink interval must be an integer number of milliseconds.")
        try:
            normalized = operator.index(interval_ms)
        except TypeError as exc:
            raise ValueError(
                "Blink interval must be an integer number of milliseconds."
            ) from exc
        minimum = self.blink_interval_spin.minimum()
        maximum = self.blink_interval_spin.maximum()
        if not minimum <= normalized <= maximum:
            raise ValueError(
                f"Blink interval must be between {minimum} and {maximum} milliseconds."
            )
        self.blink_interval_spin.setValue(normalized)

    def set_inputs(self, left_name: str | None, right_name: str | None) -> None:
        """Update passive operand labels and invalidate the previous result."""

        self._left_name = str(left_name).strip() if left_name else None
        self._right_name = str(right_name).strip() if right_name else None
        self.left_label.setText(self._left_name or self.tr("Not selected"))
        self.right_label.setText(self._right_name or self.tr("Not selected"))
        self._comparison_available = False
        self.stop_blinking()
        if self._inputs_ready():
            self.set_status(self.tr("Ready to compare."))
        else:
            self.set_status(self.tr("Choose two images to compare."))
        self._refresh_controls()

    def input_names(self) -> tuple[str | None, str | None]:
        return self._left_name, self._right_name

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        if self._busy:
            self.stop_blinking()
        self._refresh_controls()

    def set_comparison_available(self, available: bool, message: str | None = None) -> None:
        self._comparison_available = bool(available) and self._inputs_ready()
        if not self._comparison_available:
            self.stop_blinking()
        if message is not None:
            self.set_status(message)
        self._refresh_controls()

    def set_comparison_result(self, result: ImageComparisonResult) -> None:
        """Reflect a core comparison result without retaining its image arrays."""

        if result.success:
            message = result.warning or self.tr("Comparison ready.")
            self.set_comparison_available(True, message)
        else:
            self.set_comparison_available(False, result.reason or self.tr("Comparison failed."))

    def set_status(self, message: str) -> None:
        self.status_label.setText(str(message))

    def is_blinking(self) -> bool:
        return self._blink_timer.isActive()

    def stop_blinking(self) -> None:
        if self.blink_toggle_button.isChecked():
            self.blink_toggle_button.setChecked(False)
        elif self._blink_timer.isActive():
            self._blink_timer.stop()
            self.blink_active_changed.emit(False)

    def relay_zoom_state(
        self,
        source_pane: int,
        scale: float,
        center_x: float,
        center_y: float,
    ) -> None:
        """Relay a zoom state to the opposite pane when synchronization is on."""

        target = self._sync_target(source_pane)
        values = (float(scale), float(center_x), float(center_y))
        if values[0] <= 0 or not all(math.isfinite(math_value) for math_value in values):
            raise ValueError("Zoom state must contain a positive scale and finite coordinates.")
        if self.sync_views_check.isChecked():
            self.zoom_sync_requested.emit(target, *values)

    def relay_pan_state(self, source_pane: int, center_x: float, center_y: float) -> None:
        """Relay a pan center to the opposite pane when synchronization is on."""

        target = self._sync_target(source_pane)
        values = (float(center_x), float(center_y))
        if not all(math.isfinite(math_value) for math_value in values):
            raise ValueError("Pan state coordinates must be finite.")
        if self.sync_views_check.isChecked():
            self.pan_sync_requested.emit(target, *values)

    @staticmethod
    def _sync_target(source_pane: int) -> int:
        if source_pane not in (0, 1):
            raise ValueError("source_pane must be 0 (left) or 1 (right).")
        return 1 - source_pane

    def _inputs_ready(self) -> bool:
        return bool(self._left_name and self._right_name)

    def _refresh_controls(self) -> None:
        inputs_ready = self._inputs_ready()
        self.compare_button.setEnabled(inputs_ready and not self._busy)
        self.swap_button.setEnabled(inputs_ready and not self._busy)
        self.clear_button.setEnabled(bool(self._left_name or self._right_name) and not self._busy)
        self.select_left_button.setEnabled(not self._busy)
        self.select_right_button.setEnabled(not self._busy)
        blink_mode = self.mode() is ComparisonMode.BLINK
        self.blink_group.setEnabled(blink_mode)
        self.blink_toggle_button.setEnabled(
            blink_mode and self._comparison_available and not self._busy
        )

    def _request_comparison(self) -> None:
        if not self._inputs_ready() or self._busy:
            return
        self.stop_blinking()
        self._comparison_available = False
        self._refresh_controls()
        self.comparison_requested.emit(self.mode().value, self.alignment().value)

    def _request_clear(self) -> None:
        self.set_inputs(None, None)
        self.clear_requested.emit()

    def _on_mode_changed(self) -> None:
        self._comparison_available = False
        self.stop_blinking()
        self._refresh_controls()
        self.mode_changed.emit(self.mode().value)

    def _on_alignment_changed(self) -> None:
        self._comparison_available = False
        self.stop_blinking()
        self._refresh_controls()
        self.alignment_changed.emit(self.alignment().value)

    def _on_blink_interval_changed(self, interval_ms: int) -> None:
        self._blink_timer.setInterval(interval_ms)
        self.blink_interval_changed.emit(interval_ms)

    def _toggle_blink(self, checked: bool) -> None:
        if checked:
            if (
                self.mode() is not ComparisonMode.BLINK
                or not self._comparison_available
                or self._busy
            ):
                self.blink_toggle_button.setChecked(False)
                return
            self._blink_phase = 0
            self.blink_toggle_button.setText(self.tr("Stop blinking"))
            self.blink_phase_changed.emit(self._blink_phase)
            self._blink_timer.start()
            self.blink_active_changed.emit(True)
            return

        was_active = self._blink_timer.isActive()
        self._blink_timer.stop()
        self.blink_toggle_button.setText(self.tr("Start blinking"))
        if was_active:
            self.blink_active_changed.emit(False)

    def _advance_blink(self) -> None:
        if not self._blink_timer.isActive():
            return
        self._blink_phase = 1 - self._blink_phase
        self.blink_phase_changed.emit(self._blink_phase)
