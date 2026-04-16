from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class MarkerDock(QDockWidget):
    """Dock panel for drawing coordinate markers on the canvas.

    Coordinate format (one per line):
        x, y
    Lines starting with # are ignored. Empty lines are skipped.
    """

    markers_updated = Signal(list)  # list[MarkerSpec]
    color_changed = Signal(QColor)
    line_width_changed = Signal(int)
    source_color_changed = Signal(QColor)
    source_line_width_changed = Signal(int)

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__("Markers", parent)
        self.setObjectName("marker_dock")

        self._color = QColor(255, 0, 0)
        self._source_color = QColor(255, 0, 0)

        content = QWidget(self)
        layout = QVBoxLayout(content)

        # --- Imported-marker parameters ---
        param_group = QGroupBox("Imported Markers", content)
        param_form = QFormLayout(param_group)

        self.radius_spin = QDoubleSpinBox(param_group)
        self.radius_spin.setRange(1.0, 500.0)
        self.radius_spin.setValue(20.0)
        self.radius_spin.setSingleStep(1.0)
        self.radius_spin.setSuffix(" px")
        param_form.addRow("Radius:", self.radius_spin)

        self.line_width_spin = QSpinBox(param_group)
        self.line_width_spin.setRange(1, 25)
        self.line_width_spin.setValue(5)
        self.line_width_spin.valueChanged.connect(self.line_width_changed.emit)
        param_form.addRow("Line width:", self.line_width_spin)

        color_row = QWidget(param_group)
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.color_preview = QLabel(color_row)
        self.color_preview.setFixedSize(24, 24)
        self._update_color_preview()
        color_btn = QPushButton("Choose...", color_row)
        color_btn.clicked.connect(self._pick_color)
        color_layout.addWidget(self.color_preview)
        color_layout.addWidget(color_btn)
        color_layout.addStretch()
        param_form.addRow("Color:", color_row)

        layout.addWidget(param_group)

        # --- ROI / detected source parameters ---
        source_group = QGroupBox("Detected Sources (ROI)", content)
        source_form = QFormLayout(source_group)

        self.source_line_width_spin = QSpinBox(source_group)
        self.source_line_width_spin.setRange(1, 25)
        self.source_line_width_spin.setValue(5)
        self.source_line_width_spin.valueChanged.connect(self.source_line_width_changed.emit)
        source_form.addRow("Line width:", self.source_line_width_spin)

        source_color_row = QWidget(source_group)
        source_color_layout = QHBoxLayout(source_color_row)
        source_color_layout.setContentsMargins(0, 0, 0, 0)
        self.source_color_preview = QLabel(source_color_row)
        self.source_color_preview.setFixedSize(24, 24)
        self._update_source_color_preview()
        source_color_btn = QPushButton("Choose...", source_color_row)
        source_color_btn.clicked.connect(self._pick_source_color)
        source_color_layout.addWidget(self.source_color_preview)
        source_color_layout.addWidget(source_color_btn)
        source_color_layout.addStretch()
        source_form.addRow("Color:", source_color_row)

        layout.addWidget(source_group)

        # --- Single coordinate add ---
        add_group = QGroupBox("Add Coordinate", content)
        add_form = QFormLayout(add_group)

        self.coord_type = QComboBox(add_group)
        self.coord_type.addItems(["Pixel (x, y)", "WCS (ra, dec)"])
        self.coord_type.currentIndexChanged.connect(self._on_coord_type_changed)
        add_form.addRow("Type:", self.coord_type)

        self.x_label = QLabel("X:")
        self.x_spin = QDoubleSpinBox(add_group)
        self.x_spin.setRange(-1e6, 1e6)
        self.x_spin.setDecimals(6)
        add_form.addRow(self.x_label, self.x_spin)

        self.y_label = QLabel("Y:")
        self.y_spin = QDoubleSpinBox(add_group)
        self.y_spin.setRange(-1e6, 1e6)
        self.y_spin.setDecimals(6)
        add_form.addRow(self.y_label, self.y_spin)

        add_btn_row = QWidget(add_group)
        add_btn_layout = QHBoxLayout(add_btn_row)
        add_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.add_btn = QPushButton("Add", add_btn_row)
        self.add_apply_btn = QPushButton("Add && Apply", add_btn_row)
        add_btn_layout.addWidget(self.add_btn)
        add_btn_layout.addWidget(self.add_apply_btn)
        add_form.addRow(add_btn_row)
        self.add_btn.clicked.connect(self._on_add_single)
        self.add_apply_btn.clicked.connect(self._on_add_and_apply)

        layout.addWidget(add_group)

        # --- Batch coordinate input ---
        coord_label = QLabel("Batch (one per line: x, y):", content)
        layout.addWidget(coord_label)

        self.coord_input = QPlainTextEdit(content)
        self.coord_input.setPlaceholderText(
            "# Pixel: x, y\n"
            "512, 512\n"
            "100.5, 200.3\n"
            "# WCS: ra, dec (degrees)\n"
            "w 180.0, 45.0\n"
            "w 179.5, 44.8"
        )
        layout.addWidget(self.coord_input)

        self.status_label = QLabel("", content)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # --- Buttons ---
        btn_row = QWidget(content)
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self.apply_btn = QPushButton("Apply", btn_row)
        self.clear_btn = QPushButton("Clear", btn_row)
        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(self.clear_btn)
        layout.addWidget(btn_row)

        self.setWidget(content)

        self.apply_btn.clicked.connect(self._on_apply)
        self.clear_btn.clicked.connect(self._on_clear)

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor | str) -> None:
        self._color = QColor(color)
        self._update_color_preview()

    def radius(self) -> float:
        return self.radius_spin.value()

    def set_radius(self, radius: float) -> None:
        self.radius_spin.setValue(radius)

    def line_width(self) -> int:
        return self.line_width_spin.value()

    def set_line_width(self, line_width: int) -> None:
        self.line_width_spin.setValue(line_width)

    def source_color(self) -> QColor:
        return QColor(self._source_color)

    def set_source_color(self, color: QColor | str) -> None:
        self._source_color = QColor(color)
        self._update_source_color_preview()

    def source_line_width(self) -> int:
        return self.source_line_width_spin.value()

    def set_source_line_width(self, line_width: int) -> None:
        self.source_line_width_spin.setValue(line_width)

    def parse_coordinates(self) -> list[tuple[str, float, float]]:
        """Parse text input into (type, v1, v2) tuples.

        Returns ('pixel', x, y) or ('wcs', ra, dec) per line.
        Lines prefixed with 'w ' are WCS; otherwise pixel.
        """

        coords, _errors = self.parse_coordinates_with_feedback()
        return coords

    def parse_coordinates_with_feedback(self) -> tuple[list[tuple[str, float, float]], list[str]]:
        """Parse coordinates and return both valid entries and line-specific errors."""

        coords: list[tuple[str, float, float]] = []
        errors: list[str] = []
        for line_number, raw_line in enumerate(self.coord_input.toPlainText().splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            coord_type = "pixel"
            if line.lower().startswith("w "):
                coord_type = "wcs"
                line = line[2:].strip()
            parts = line.split(",")
            if len(parts) != 2:
                errors.append(f"Line {line_number}: expected two comma-separated values.")
                continue
            try:
                v1, v2 = float(parts[0].strip()), float(parts[1].strip())
                coords.append((coord_type, v1, v2))
            except ValueError:
                errors.append(f"Line {line_number}: values must be numeric.")
        return coords, errors

    def _on_apply(self) -> None:
        entries, errors = self.parse_coordinates_with_feedback()
        if not entries:
            if errors:
                self.status_label.setText("No valid coordinates found. " + " ".join(errors[:3]))
            else:
                self.status_label.setText("No valid coordinates found.")
            return
        if errors:
            self.status_label.setText(
                f"{len(entries)} marker(s). Skipped {len(errors)} invalid line(s): "
                + ", ".join(error.split(":")[0] for error in errors[:5])
            )
        else:
            self.status_label.setText(f"{len(entries)} marker(s)")
        self.markers_updated.emit(entries)

    def _on_add_single(self) -> None:
        self._append_current_xy()

    def _on_add_and_apply(self) -> None:
        self._append_current_xy()
        self._on_apply()

    def _append_current_xy(self) -> None:
        v1 = self.x_spin.value()
        v2 = self.y_spin.value()
        is_wcs = self.coord_type.currentIndex() == 1
        if is_wcs:
            line = f"w {v1}, {v2}"
        else:
            line = f"{v1}, {v2}"
        self.coord_input.appendPlainText(line)

    def _on_clear(self) -> None:
        self.coord_input.clear()
        self.markers_updated.emit([])
        self.status_label.setText("Cleared.")

    def _on_coord_type_changed(self, index: int) -> None:
        if index == 1:
            self.x_label.setText("RA (deg):")
            self.y_label.setText("Dec (deg):")
            self.x_spin.setRange(-360, 360)
            self.y_spin.setRange(-90, 90)
        else:
            self.x_label.setText("X:")
            self.y_label.setText("Y:")
            self.x_spin.setRange(-1e6, 1e6)
            self.y_spin.setRange(-1e6, 1e6)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, "Marker Color")
        if color.isValid():
            self._color = color
            self._update_color_preview()
            self.color_changed.emit(self.color())

    def _pick_source_color(self) -> None:
        color = QColorDialog.getColor(self._source_color, self, "Source Overlay Color")
        if color.isValid():
            self._source_color = color
            self._update_source_color_preview()
            self.source_color_changed.emit(self.source_color())

    def _update_color_preview(self) -> None:
        self.color_preview.setStyleSheet(
            f"background-color: {self._color.name()}; border: 1px solid gray;"
        )

    def _update_source_color_preview(self) -> None:
        self.source_color_preview.setStyleSheet(
            f"background-color: {self._source_color.name()}; border: 1px solid gray;"
        )
