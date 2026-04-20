from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Signal, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QMouseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_HANDLE_HIT_PX = 10


class _HistogramView(QWidget):
    """Lightweight histogram preview drawn without extra plotting dependencies."""

    range_dragged = Signal(float, float)
    range_drag_finished = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts = np.zeros(0, dtype=np.int64)
        self._manual_low: float | None = None
        self._manual_high: float | None = None
        self._dragging: str | None = None  # "low", "high", or None
        self.setMinimumHeight(140)
        self.setMouseTracking(True)

    def set_histogram(self, counts: np.ndarray) -> None:
        self._counts = np.asarray(counts, dtype=np.int64)
        self.update()

    def set_manual_range(self, low: float | None, high: float | None) -> None:
        self._manual_low = low
        self._manual_high = high
        self.update()

    def clear(self) -> None:
        self._counts = np.zeros(0, dtype=np.int64)
        self._manual_low = None
        self._manual_high = None
        self._dragging = None
        self.update()

    def _chart_rect(self) -> QRectF:
        return QRectF(self.rect().adjusted(8, 8, -8, -8))

    def _ratio_to_x(self, ratio: float) -> float:
        r = self._chart_rect()
        return r.left() + min(max(ratio, 0.0), 1.0) * r.width()

    def _x_to_ratio(self, x: float) -> float:
        r = self._chart_rect()
        if r.width() <= 0:
            return 0.0
        return min(max((x - r.left()) / r.width(), 0.0), 1.0)

    def _hit_handle(self, x: float) -> str | None:
        if self._manual_low is None or self._manual_high is None:
            return None
        low_x = self._ratio_to_x(self._manual_low)
        high_x = self._ratio_to_x(self._manual_high)
        dist_low = abs(x - low_x)
        dist_high = abs(x - high_x)
        if dist_low <= _HANDLE_HIT_PX and dist_low <= dist_high:
            return "low"
        if dist_high <= _HANDLE_HIT_PX:
            return "high"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._hit_handle(event.position().x())
            if handle is not None:
                self._dragging = handle
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging is not None:
            ratio = self._x_to_ratio(event.position().x())
            if self._dragging == "low":
                high = self._manual_high if self._manual_high is not None else 1.0
                self._manual_low = min(ratio, high - 0.001)
            else:
                low = self._manual_low if self._manual_low is not None else 0.0
                self._manual_high = max(ratio, low + 0.001)
            self.update()
            if self._manual_low is not None and self._manual_high is not None:
                self.range_dragged.emit(self._manual_low, self._manual_high)
            event.accept()
            return

        handle = self._hit_handle(event.position().x())
        if handle is not None:
            self.setCursor(QCursor(Qt.CursorShape.SplitHCursor))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging is not None and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = None
            if self._manual_low is not None and self._manual_high is not None:
                self.range_drag_finished.emit(self._manual_low, self._manual_high)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._chart_rect().toAlignedRect()

        painter.fillRect(rect, QColor("#101419"))
        painter.setPen(QPen(QColor("#2e3b4a"), 1))
        painter.drawRect(rect)

        if self._counts.size == 0 or rect.width() <= 0 or rect.height() <= 0:
            painter.setPen(QColor("#8ea0b5"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.tr("No histogram"))
            return

        counts = np.log1p(self._counts.astype(np.float64))
        peak = float(np.max(counts))
        if peak <= 0:
            peak = 1.0

        path = QPainterPath()
        width = rect.width()
        height = rect.height()
        for index, count in enumerate(counts):
            x = rect.left() + (index / max(1, counts.size - 1)) * width
            y = rect.bottom() - (count / peak) * height
            point = QPointF(x, y)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)

        fill_path = QPainterPath(path)
        fill_path.lineTo(rect.bottomRight())
        fill_path.lineTo(rect.bottomLeft())
        fill_path.closeSubpath()

        painter.fillPath(fill_path, QColor(98, 168, 255, 70))
        painter.setPen(QPen(QColor("#62a8ff"), 1.5))
        painter.drawPath(path)

        if self._manual_low is None or self._manual_high is None:
            return

        low_x = self._ratio_to_x(self._manual_low)
        high_x = self._ratio_to_x(self._manual_high)

        # shaded regions outside the selected range
        shade = QColor(0, 0, 0, 120)
        painter.fillRect(QRectF(rect.left(), rect.top(), low_x - rect.left(), rect.height()), shade)
        painter.fillRect(QRectF(high_x, rect.top(), rect.right() - high_x, rect.height()), shade)

        # handle lines: dark shadow first for contrast, then bright core line
        shadow_pen = QPen(QColor(0, 0, 0, 200), 5)
        painter.setPen(shadow_pen)
        painter.drawLine(QPointF(low_x, rect.top()), QPointF(low_x, rect.bottom()))
        painter.drawLine(QPointF(high_x, rect.top()), QPointF(high_x, rect.bottom()))

        handle_pen = QPen(QColor("#ffcf5a"), 3)
        painter.setPen(handle_pen)
        painter.drawLine(QPointF(low_x, rect.top()), QPointF(low_x, rect.bottom()))
        painter.drawLine(QPointF(high_x, rect.top()), QPointF(high_x, rect.bottom()))

        # triangular grips at BOTH top and bottom of each handle, with dark outline
        grip_size = 7.0
        grip_color = QColor("#ffcf5a")
        grip_outline = QPen(QColor(0, 0, 0, 220), 1.5)
        for hx in (low_x, high_x):
            # bottom grip (pointing down into the bottom margin)
            bottom_grip = QPainterPath()
            bottom_grip.moveTo(hx, rect.bottom())
            bottom_grip.lineTo(hx - grip_size, rect.bottom() + grip_size)
            bottom_grip.lineTo(hx + grip_size, rect.bottom() + grip_size)
            bottom_grip.closeSubpath()
            painter.fillPath(bottom_grip, grip_color)
            painter.setPen(grip_outline)
            painter.drawPath(bottom_grip)

            # top grip (pointing up into the top margin)
            top_grip = QPainterPath()
            top_grip.moveTo(hx, rect.top())
            top_grip.lineTo(hx - grip_size, rect.top() - grip_size)
            top_grip.lineTo(hx + grip_size, rect.top() - grip_size)
            top_grip.closeSubpath()
            painter.fillPath(top_grip, grip_color)
            painter.setPen(grip_outline)
            painter.drawPath(top_grip)


class HistogramDock(QDockWidget):
    """Dock panel for manual image display limits and histogram inspection."""

    manual_range_applied = Signal(float, float)
    auto_range_requested = Signal()

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("histogram_dock")
        self.setWindowTitle(self.tr("Histogram"))

        self._data_min = 0.0
        self._data_max = 0.0

        content = QWidget(self)
        layout = QVBoxLayout(content)

        self.range_label = QLabel(self.tr("Range: -"), content)
        self.range_label.setWordWrap(True)
        self.histogram_view = _HistogramView(content)
        layout.addWidget(self.range_label)
        layout.addWidget(self.histogram_view)

        low_row = QWidget(content)
        low_layout = QHBoxLayout(low_row)
        low_layout.setContentsMargins(0, 0, 0, 0)
        self.low_spin = QDoubleSpinBox(low_row)
        self.high_spin = QDoubleSpinBox(low_row)
        for spin in (self.low_spin, self.high_spin):
            spin.setDecimals(6)
            spin.setRange(-1.0e18, 1.0e18)
            spin.setKeyboardTracking(False)
            spin.setSingleStep(0.1)
        low_layout.addWidget(QLabel(self.tr("Low:"), low_row))
        low_layout.addWidget(self.low_spin, 1)
        low_layout.addWidget(QLabel(self.tr("High:"), low_row))
        low_layout.addWidget(self.high_spin, 1)
        layout.addWidget(low_row)

        button_row = QWidget(content)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.apply_btn = QPushButton(self.tr("Apply Manual Range"), button_row)
        self.auto_btn = QPushButton(self.tr("Use Auto Interval"), button_row)
        button_layout.addWidget(self.apply_btn)
        button_layout.addWidget(self.auto_btn)
        layout.addWidget(button_row)

        self.status_label = QLabel("", content)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch()

        self.setWidget(content)

        self.apply_btn.clicked.connect(self._emit_manual_range)
        self.auto_btn.clicked.connect(self.auto_range_requested.emit)
        self.histogram_view.range_dragged.connect(self._on_range_dragged)
        self.histogram_view.range_drag_finished.connect(self._on_range_drag_finished)

    def set_histogram(
        self,
        counts: np.ndarray,
        min_value: float,
        max_value: float,
        *,
        manual_limits: tuple[float, float] | None = None,
    ) -> None:
        """Update histogram data, value range, and optional manual markers."""

        self._data_min = float(min_value)
        self._data_max = float(max_value)
        self.range_label.setText(self.tr("Range: {low:.6f} .. {high:.6f}").format(
            low=self._data_min,
            high=self._data_max,
        ))
        self.histogram_view.set_histogram(counts)

        low_value = self._data_min
        high_value = self._data_max
        if manual_limits is not None:
            low_value, high_value = manual_limits

        self.low_spin.blockSignals(True)
        self.high_spin.blockSignals(True)
        self.low_spin.setValue(float(low_value))
        self.high_spin.setValue(float(high_value))
        self.low_spin.blockSignals(False)
        self.high_spin.blockSignals(False)

        self.histogram_view.set_manual_range(
            self._to_ratio(low_value),
            self._to_ratio(high_value),
        )
        self.status_label.clear()

    def clear_histogram(self) -> None:
        """Reset the dock to its empty state."""

        self._data_min = 0.0
        self._data_max = 0.0
        self.range_label.setText(self.tr("Range: -"))
        self.histogram_view.clear()
        self.low_spin.setValue(0.0)
        self.high_spin.setValue(0.0)
        self.status_label.clear()

    def _from_ratio(self, ratio: float) -> float:
        return self._data_min + ratio * (self._data_max - self._data_min)

    def _on_range_dragged(self, low_ratio: float, high_ratio: float) -> None:
        """Live-update spin boxes while dragging."""
        low = self._from_ratio(low_ratio)
        high = self._from_ratio(high_ratio)
        self.low_spin.blockSignals(True)
        self.high_spin.blockSignals(True)
        self.low_spin.setValue(low)
        self.high_spin.setValue(high)
        self.low_spin.blockSignals(False)
        self.high_spin.blockSignals(False)

    def _on_range_drag_finished(self, low_ratio: float, high_ratio: float) -> None:
        """Apply the range when the user releases the handle."""
        low = self._from_ratio(low_ratio)
        high = self._from_ratio(high_ratio)
        if high <= low:
            return
        self.status_label.setText(self.tr("Manual range applied."))
        self.manual_range_applied.emit(low, high)

    def _emit_manual_range(self) -> None:
        low = float(self.low_spin.value())
        high = float(self.high_spin.value())
        if high <= low:
            self.status_label.setText(self.tr("High must be greater than low."))
            return

        self.status_label.setText(self.tr("Manual range applied."))
        self.histogram_view.set_manual_range(self._to_ratio(low), self._to_ratio(high))
        self.manual_range_applied.emit(low, high)

    def _to_ratio(self, value: float) -> float | None:
        span = self._data_max - self._data_min
        if span <= 0:
            return None
        return (float(value) - self._data_min) / span
