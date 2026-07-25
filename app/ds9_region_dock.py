"""Standalone controls for safe DS9 Region import and export."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.ds9_regions import (
    DEFAULT_DS9_REGION_LIMITS,
    DS9Attribute,
    DS9Diagnostic,
    DS9Region,
    DS9RegionDocument,
    DS9RegionError,
    DS9RegionLimitError,
    DS9RegionLimits,
    read_ds9_region_file,
    serialize_ds9_regions,
    write_ds9_region_file,
)


MAX_REGION_TABLE_ROWS = 2_000
_ERROR_TEXT_LIMIT = 512
_T = TypeVar("_T")


class DS9RegionDock(QDockWidget):
    """Own a bounded DS9 document without depending on a canvas or main window.

    Hosts can connect :attr:`document_changed` to their overlay adapter and
    :attr:`overlay_visibility_changed` to their renderer.  File parsing and
    writing stay in the core module; this dock only coordinates user actions
    and presents a bounded preview of the document.
    """

    document_changed = Signal(object)  # DS9RegionDocument
    overlay_visibility_changed = Signal(bool)
    region_selected = Signal(int)  # document index, or -1
    file_loaded = Signal(str)
    file_saved = Signal(str)
    operation_failed = Signal(str, str)  # operation, safe display message
    capture_roi_requested = Signal()
    capture_aperture_requested = Signal()

    def __init__(
        self,
        parent: Any | None = None,
        *,
        limits: DS9RegionLimits = DEFAULT_DS9_REGION_LIMITS,
        max_table_rows: int = MAX_REGION_TABLE_ROWS,
    ) -> None:
        super().__init__(parent)
        if not isinstance(limits, DS9RegionLimits):
            raise TypeError("limits must be a DS9RegionLimits instance.")
        if isinstance(max_table_rows, bool) or not isinstance(max_table_rows, int):
            raise TypeError("max_table_rows must be an integer.")
        if max_table_rows <= 0 or max_table_rows > limits.max_regions:
            raise ValueError("max_table_rows must be between 1 and the region limit.")

        self._limits = limits
        self._max_table_rows = max_table_rows
        self._document = DS9RegionDocument()
        self._source_path: Path | None = None

        self.setObjectName("ds9_region_dock")
        self.setWindowTitle(self.tr("DS9 Regions"))

        content = QWidget(self)
        layout = QVBoxLayout(content)

        self.summary_label = QLabel(self.tr("No regions loaded."), content)
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.show_regions_checkbox = QCheckBox(self.tr("Show region overlay"), content)
        self.show_regions_checkbox.setChecked(True)
        self.show_regions_checkbox.setEnabled(False)
        layout.addWidget(self.show_regions_checkbox)

        self.table = QTableWidget(0, 6, content)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("#"),
                self.tr("System"),
                self.tr("Shape"),
                self.tr("Mode"),
                self.tr("Label"),
                self.tr("Color"),
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        capture_actions = QWidget(content)
        capture_layout = QHBoxLayout(capture_actions)
        capture_layout.setContentsMargins(0, 0, 0, 0)
        self.capture_roi_button = QPushButton(self.tr("Add Current ROI"), capture_actions)
        self.capture_aperture_button = QPushButton(self.tr("Add Current Aperture"), capture_actions)
        self.capture_roi_button.setEnabled(False)
        self.capture_aperture_button.setEnabled(False)
        capture_layout.addWidget(self.capture_roi_button)
        capture_layout.addWidget(self.capture_aperture_button)
        layout.addWidget(capture_actions)

        actions = QWidget(content)
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.import_button = QPushButton(self.tr("Import..."), actions)
        self.export_button = QPushButton(self.tr("Export..."), actions)
        self.clear_button = QPushButton(self.tr("Clear"), actions)
        self.export_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        action_layout.addWidget(self.import_button)
        action_layout.addWidget(self.export_button)
        action_layout.addWidget(self.clear_button)
        layout.addWidget(actions)

        self.status_label = QLabel(self.tr("Ready to import a DS9 Region file."), content)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.setWidget(content)

        self.import_button.clicked.connect(self._choose_import_file)
        self.export_button.clicked.connect(self._choose_export_file)
        self.clear_button.clicked.connect(self.clear_regions)
        self.capture_roi_button.clicked.connect(self.capture_roi_requested.emit)
        self.capture_aperture_button.clicked.connect(self.capture_aperture_requested.emit)
        self.show_regions_checkbox.toggled.connect(self.overlay_visibility_changed.emit)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)

    def limits(self) -> DS9RegionLimits:
        return self._limits

    def document(self) -> DS9RegionDocument:
        return self._document

    def source_path(self) -> Path | None:
        return self._source_path

    def overlay_visible(self) -> bool:
        return self.show_regions_checkbox.isChecked()

    def set_overlay_visible(self, visible: bool) -> None:
        self.show_regions_checkbox.setChecked(bool(visible))

    def set_capture_enabled(self, *, roi: bool, aperture: bool) -> None:
        self.capture_roi_button.setEnabled(bool(roi))
        self.capture_aperture_button.setEnabled(bool(aperture))

    def set_document(
        self,
        document: DS9RegionDocument,
        *,
        source_path: str | Path | None = None,
        emit_change: bool = True,
    ) -> None:
        """Validate, copy, and display a document within this dock's budgets."""

        normalized = self._normalize_document(document)
        # Serialization applies shape, attribute, line, and total-output
        # budgets to programmatically supplied documents as well as imports.
        serialize_ds9_regions(normalized, limits=self._limits)

        self._document = normalized
        self._source_path = Path(source_path) if source_path is not None else None
        self._refresh_document_view()
        if emit_change:
            self.document_changed.emit(self._document)

    def load_file(self, path: str | Path, *, strict: bool = False) -> DS9RegionDocument:
        """Load one local regular file and replace the current document.

        On failure, the prior document is kept.  The exception is re-raised so
        non-UI callers can decide how to report or recover from it.
        """

        try:
            document = read_ds9_region_file(path, strict=strict, limits=self._limits)
            self.set_document(document, source_path=path)
        except (OSError, DS9RegionError, TypeError, ValueError) as exc:
            self._report_failure("import", exc)
            raise

        resolved = str(Path(path))
        self.file_loaded.emit(resolved)
        warning_count = len(document.diagnostics)
        if warning_count:
            self.status_label.setText(
                self.tr("Imported {count} region(s); skipped or warned about {warnings} record(s).").format(
                    count=len(document.regions),
                    warnings=warning_count,
                )
            )
        else:
            self.status_label.setText(
                self.tr("Imported {count} region(s).").format(count=len(document.regions))
            )
        return document

    def save_file(self, path: str | Path, *, overwrite: bool = False) -> None:
        """Export the current document through the bounded atomic writer."""

        try:
            write_ds9_region_file(
                path,
                self._document,
                overwrite=overwrite,
                limits=self._limits,
            )
        except (OSError, DS9RegionError, TypeError, ValueError) as exc:
            self._report_failure("export", exc)
            raise

        resolved = str(Path(path))
        self.file_saved.emit(resolved)
        self.status_label.setText(
            self.tr("Exported {count} region(s).").format(count=len(self._document.regions))
        )

    def clear_regions(self) -> None:
        if (
            not self._document.regions
            and not self._document.global_attributes
            and not self._document.diagnostics
            and self._source_path is None
        ):
            return
        self._document = DS9RegionDocument()
        self._source_path = None
        self._refresh_document_view()
        self.status_label.setText(self.tr("Regions cleared."))
        self.document_changed.emit(self._document)

    def set_status(self, message: str) -> None:
        self.status_label.setText(_safe_display_text(message))

    def _normalize_document(self, document: DS9RegionDocument) -> DS9RegionDocument:
        if not isinstance(document, DS9RegionDocument):
            raise TypeError("document must be a DS9RegionDocument.")
        regions = _bounded_tuple(document.regions, self._limits.max_regions, "regions")
        global_attributes = _bounded_tuple(
            document.global_attributes,
            self._limits.max_attributes_per_record,
            "global attributes",
        )
        diagnostics = _bounded_tuple(
            document.diagnostics,
            self._limits.max_diagnostics,
            "diagnostics",
        )
        if not all(isinstance(item, DS9Region) for item in regions):
            raise TypeError("document regions must be DS9Region objects.")
        if not all(isinstance(item, DS9Attribute) for item in global_attributes):
            raise TypeError("global attributes must be DS9Attribute objects.")
        if not all(isinstance(item, DS9Diagnostic) for item in diagnostics):
            raise TypeError("diagnostics must be DS9Diagnostic objects.")
        return DS9RegionDocument(
            regions=regions,
            global_attributes=global_attributes,
            diagnostics=diagnostics,
        )

    def _refresh_document_view(self) -> None:
        regions = self._document.regions
        shown = min(len(regions), self._max_table_rows)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearContents()
            self.table.setRowCount(shown)
            for row, region in enumerate(regions[:shown]):
                effective = self._document.effective_attributes(region)
                label = _last_attribute(effective, ("text", "label")) or ""
                color = _last_attribute(effective, ("color",)) or ""
                values = (
                    str(row + 1),
                    region.coordinate_system,
                    region.shape,
                    self.tr("Include") if region.include else self.tr("Exclude"),
                    label,
                    color,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, row)
                    if column == 5 and color:
                        swatch = QColor(color)
                        if swatch.isValid():
                            item.setBackground(swatch)
                            if swatch.lightness() < 128:
                                item.setForeground(QColor("white"))
                    self.table.setItem(row, column, item)
        finally:
            self.table.setUpdatesEnabled(True)

        has_regions = bool(regions)
        self.show_regions_checkbox.setEnabled(has_regions)
        self.export_button.setEnabled(has_regions)
        self.clear_button.setEnabled(
            has_regions
            or bool(self._document.global_attributes)
            or bool(self._document.diagnostics)
            or self._source_path is not None
        )

        if not regions:
            self.summary_label.setText(self.tr("No regions loaded."))
        elif shown < len(regions):
            self.summary_label.setText(
                self.tr("{count} region(s); showing the first {shown}.").format(
                    count=len(regions), shown=shown
                )
            )
        else:
            self.summary_label.setText(
                self.tr("{count} region(s) loaded.").format(count=len(regions))
            )

    def _choose_import_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("Import DS9 Regions"),
            "",
            self.tr("DS9 Region Files (*.reg);;All Files (*)"),
        )
        if not path:
            return
        try:
            self.load_file(path)
        except (OSError, DS9RegionError, TypeError, ValueError):
            # load_file already updates the non-modal status and failure signal.
            return

    def _choose_export_file(self) -> None:
        if not self._document.regions:
            return
        suggested = "regions.reg"
        if self._source_path is not None:
            suggested = str(self._source_path)
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Export DS9 Regions"),
            suggested,
            self.tr("DS9 Region Files (*.reg);;All Files (*)"),
        )
        if not path:
            return
        try:
            # QFileDialog has already obtained explicit overwrite consent.
            self.save_file(path, overwrite=True)
        except (OSError, DS9RegionError, TypeError, ValueError):
            return

    def _on_current_cell_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if 0 <= current_row < len(self._document.regions):
            self.region_selected.emit(current_row)
        else:
            self.region_selected.emit(-1)

    def _report_failure(self, operation: str, error: Exception) -> None:
        message = _safe_display_text(str(error) or error.__class__.__name__)
        if operation == "import":
            status = self.tr("Region import failed: {detail}").format(detail=message)
        else:
            status = self.tr("Region export failed: {detail}").format(detail=message)
        self.status_label.setText(status)
        self.operation_failed.emit(operation, message)


def _bounded_tuple(values: Iterable[_T], maximum: int, label: str) -> tuple[_T, ...]:
    result: list[_T] = []
    for value in values:
        if len(result) >= maximum:
            raise DS9RegionLimitError(f"Document contains more than {maximum:,} {label}.")
        result.append(value)
    return tuple(result)


def _last_attribute(
    attributes: tuple[DS9Attribute, ...],
    names: tuple[str, ...],
) -> str | None:
    accepted = frozenset(names)
    for attribute in reversed(attributes):
        if attribute.name in accepted:
            return attribute.value
    return None


def _safe_display_text(value: Any) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = "".join(
        char
        for char in text
        if ord(char) >= 32
        and ord(char) != 127
        and not 0xD800 <= ord(char) <= 0xDFFF
        and char
        not in {"\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"}
    )
    if len(text) > _ERROR_TEXT_LIMIT:
        return text[: _ERROR_TEXT_LIMIT - 1] + "…"
    return text


__all__ = ["DS9RegionDock", "MAX_REGION_TABLE_ROWS"]
