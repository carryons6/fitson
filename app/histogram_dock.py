from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Signal, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QDockWidget,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _HistogramView(QWidget):
    """Lightweight histogram preview drawn without extra plotting dependencies."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts = np.zeros(0, dtype=np.int64)
        self._manual_low: float | None = None
        self._manual_high: float | None = None
        self.setMinimumHeight(140)

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
        self.update()

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(8, 8, -8, -8)

        painter.fillRect(rect, QColor("#101419"))
        painter.setPen(QPen(QColor("#2e3b4a"), 1))
        painter.drawRect(rect)

        if self._counts.size == 0 or rect.width() <= 0 or rect.height() <= 0:
            painter.setPen(QColor("#8ea0b5"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No histogram")
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

        manual_pen = QPen(QColor("#ffcf5a"), 1)
        manual_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(manual_pen)
        left_x = rect.left() + min(max(self._manual_low, 0.0), 1.0) * width
        right_x = rect.left() + min(max(self._manual_high, 0.0), 1.0) * width
        painter.drawLine(QPointF(left_x, rect.top()), QPointF(left_x, rect.bottom()))
        painter.drawLine(QPointF(right_x, rect.top()), QPointF(right_x, rect.bottom()))


class HistogramDock(QDockWidget):
    """Dock panel for manual image display limits and histogram inspection."""

    manual_range_applied = Signal(float, float)
    auto_range_requested = Signal()

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__("Histogram", parent)
        self.setObjectName("histogram_dock")

        self._data_min = 0.0
        self._data_max = 0.0

        content = QWidget(self)
        layout = QVBoxLayout(content)

        self.range_label = QLabel("Range: -", content)
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
        low_layout.addWidget(QLabel("Low:", low_row))
        low_layout.addWidget(self.low_spin, 1)
        low_layout.addWidget(QLabel("High:", low_row))
        low_layout.addWidget(self.high_spin, 1)
        layout.addWidget(low_row)

        button_row = QWidget(content)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.apply_btn = QPushButton("Apply Manual Range", button_row)
        self.auto_btn = QPushButton("Use Auto Interval", button_row)
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
        self.range_label.setText(
            f"Range: {self._data_min:.6f} .. {self._data_max:.6f}"
        )
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
        self.range_label.setText("Range: -")
        self.histogram_view.clear()
        self.low_spin.setValue(0.0)
        self.high_spin.setValue(0.0)
        self.status_label.clear()

    def _emit_manual_range(self) -> None:
        low = float(self.low_spin.value())
        high = float(self.high_spin.value())
        if high <= low:
            self.status_label.setText("High must be greater than low.")
            return

        self.status_label.setText("Manual range applied.")
        self.histogram_view.set_manual_range(self._to_ratio(low), self._to_ratio(high))
        self.manual_range_applied.emit(low, high)

    def _to_ratio(self, value: float) -> float | None:
        span = self._data_max - self._data_min
        if span <= 0:
            return None
        return (float(value) - self._data_min) / span
