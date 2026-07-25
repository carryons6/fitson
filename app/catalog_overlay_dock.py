from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.catalog_service import CatalogSource, MAX_CATALOG_ROWS


class CatalogOverlayDock(QDockWidget):
    """Controls WCS-grid visibility and bounded Gaia DR3 overlays."""

    grid_toggled = Signal(bool)
    query_requested = Signal(float, int, float)
    clear_requested = Signal()
    source_selected = Signal(int)

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("catalog_overlay_dock")
        self.setWindowTitle(self.tr("WCS & Catalog"))
        self._has_wcs = False
        self._query_running = False

        content = QWidget(self)
        layout = QVBoxLayout(content)

        wcs_group = QGroupBox(self.tr("Sky Coordinates"), content)
        wcs_layout = QVBoxLayout(wcs_group)
        self.center_label = QLabel(self.tr("No celestial WCS in the current frame."), wcs_group)
        self.center_label.setWordWrap(True)
        self.grid_checkbox = QCheckBox(self.tr("Show RA/Dec grid"), wcs_group)
        self.grid_checkbox.setEnabled(False)
        self.grid_checkbox.toggled.connect(self.grid_toggled.emit)
        wcs_layout.addWidget(self.center_label)
        wcs_layout.addWidget(self.grid_checkbox)
        layout.addWidget(wcs_group)

        query_group = QGroupBox(self.tr("Gaia DR3 Cone Search"), content)
        query_form = QFormLayout(query_group)
        self.radius_spin = QDoubleSpinBox(query_group)
        self.radius_spin.setRange(0.1, 120.0)
        self.radius_spin.setDecimals(1)
        self.radius_spin.setValue(10.0)
        self.radius_spin.setSuffix(" arcmin")
        query_form.addRow(self.tr("Radius:"), self.radius_spin)

        self.limit_spin = QSpinBox(query_group)
        self.limit_spin.setRange(1, MAX_CATALOG_ROWS)
        self.limit_spin.setValue(500)
        query_form.addRow(self.tr("Maximum sources:"), self.limit_spin)

        self.faint_limit_spin = QDoubleSpinBox(query_group)
        self.faint_limit_spin.setRange(-10.0, 30.0)
        self.faint_limit_spin.setDecimals(1)
        self.faint_limit_spin.setValue(20.0)
        self.faint_limit_spin.setSuffix(" mag")
        query_form.addRow(self.tr("Faint G limit:"), self.faint_limit_spin)

        buttons = QWidget(query_group)
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.query_button = QPushButton(self.tr("Query Gaia"), buttons)
        self.clear_button = QPushButton(self.tr("Clear"), buttons)
        self.query_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.query_button.clicked.connect(self._emit_query)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        button_layout.addWidget(self.query_button)
        button_layout.addWidget(self.clear_button)
        query_form.addRow(buttons)
        layout.addWidget(query_group)

        self.status_label = QLabel(self.tr("Load a WCS-enabled FITS image to query Gaia."), content)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 4, content)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Source ID"), self.tr("RA"), self.tr("Dec"), self.tr("G mag")]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellClicked.connect(lambda row, _column: self.source_selected.emit(row))
        layout.addWidget(self.table, 1)

        self.setWidget(content)

    def set_wcs_state(
        self,
        has_wcs: bool,
        *,
        center_ra_deg: float | None = None,
        center_dec_deg: float | None = None,
        suggested_radius_arcmin: float | None = None,
    ) -> None:
        self._has_wcs = bool(has_wcs)
        self.grid_checkbox.setEnabled(self._has_wcs)
        self.query_button.setEnabled(self._has_wcs and not self._query_running)
        if not self._has_wcs:
            self.grid_checkbox.setChecked(False)
            self.center_label.setText(self.tr("No celestial WCS in the current frame."))
            self.status_label.setText(self.tr("Load a WCS-enabled FITS image to query Gaia."))
            return
        if center_ra_deg is not None and center_dec_deg is not None:
            self.center_label.setText(
                self.tr("Center: RA {ra:.6f}°, Dec {dec:.6f}°").format(
                    ra=center_ra_deg,
                    dec=center_dec_deg,
                )
            )
        if suggested_radius_arcmin is not None:
            self.radius_spin.setValue(max(0.1, min(120.0, suggested_radius_arcmin)))
        self.status_label.setText(self.tr("Ready to query Gaia DR3."))

    def _emit_query(self) -> None:
        if not self._has_wcs:
            return
        self.query_requested.emit(
            self.radius_spin.value(),
            self.limit_spin.value(),
            self.faint_limit_spin.value(),
        )

    def set_query_running(self, running: bool) -> None:
        self._query_running = bool(running)
        self.query_button.setEnabled(self._has_wcs and not self._query_running)
        self.radius_spin.setEnabled(not self._query_running)
        self.limit_spin.setEnabled(not self._query_running)
        self.faint_limit_spin.setEnabled(not self._query_running)
        if self._query_running:
            self.status_label.setText(self.tr("Querying Gaia DR3..."))

    def set_sources(self, sources: list[CatalogSource]) -> None:
        self.table.setRowCount(len(sources))
        for row, source in enumerate(sources):
            values = (
                source.source_id,
                f"{source.ra_deg:.6f}",
                f"{source.dec_deg:.6f}",
                "" if source.g_mag is None else f"{source.g_mag:.3f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        self.clear_button.setEnabled(bool(sources))
        self.status_label.setText(
            self.tr("Showing {count} Gaia source(s).").format(count=len(sources))
        )

    def clear_sources(self) -> None:
        self.table.setRowCount(0)
        self.clear_button.setEnabled(False)
        self.status_label.setText(
            self.tr("Ready to query Gaia DR3.")
            if self._has_wcs
            else self.tr("Load a WCS-enabled FITS image to query Gaia.")
        )

    def set_error(self, detail: str) -> None:
        self.status_label.setText(self.tr("Gaia query failed: {detail}").format(detail=detail))
