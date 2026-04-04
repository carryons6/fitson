from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .contracts import TableColumnSpec, TableRowViewModel, TableSelectionState, TableViewState, ViewFeedbackState
from ..core.source_catalog import SourceCatalog


class SourceTableDock(QDockWidget):
    """Dockable source-table skeleton.

    View contract:
    - Input from `MainWindow`: source catalog and selection changes.
    - Output to `MainWindow`: clicked row index.
    """

    source_clicked = Signal(int)
    filter_changed = Signal(str)
    MANDATORY_COLUMN_KEYS = ("ID", "X", "Y")

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.catalog: SourceCatalog | None = None
        self.columns: list[TableColumnSpec] = []
        self.rows: list[TableRowViewModel] = []
        self.filtered_rows: list[TableRowViewModel] = []
        self.selection_state = TableSelectionState()
        self.view_state = TableViewState()
        self.content_widget = QWidget(self)
        self.layout = QVBoxLayout(self.content_widget)
        self.feedback_label = QLabel("No Sources", self.content_widget)
        self.filter_input = QLineEdit(self.content_widget)
        self.summary_label = QLabel("", self.content_widget)
        self.table_widget = QTableWidget(self.content_widget)
        self.detail_label = QLabel("Target Details", self.content_widget)
        self.detail_view = QPlainTextEdit(self.content_widget)
        self.cutout_label = QLabel("Cutout Preview", self.content_widget)
        self.cutout_view = QLabel(self.content_widget)

        self.setObjectName("source_table_dock")
        self.setWindowTitle("Source Table")
        self.filter_input.setPlaceholderText("Filter sources")
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSortingEnabled(True)
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlaceholderText("Select a source to inspect its detailed fields.")
        self.detail_view.setMaximumBlockCount(256)
        self.cutout_view.setMinimumSize(160, 160)
        self.cutout_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cutout_view.setStyleSheet("background: #101419; border: 1px solid #2e3b4a;")
        self.cutout_view.setText("Select a source\nto preview its cutout.")
        self.layout.addWidget(self.feedback_label)
        self.layout.addWidget(self.filter_input)
        self.layout.addWidget(self.summary_label)
        self.layout.addWidget(self.table_widget)
        self.layout.addWidget(self.detail_label)
        self.layout.addWidget(self.detail_view)
        self.layout.addWidget(self.cutout_label)
        self.layout.addWidget(self.cutout_view)
        self.setWidget(self.content_widget)
        self.configure_columns(self.default_columns())
        self.table_widget.itemSelectionChanged.connect(self._emit_selection_changed)
        self.filter_input.textChanged.connect(self._handle_filter_changed)
        self._apply_view_state()

    def default_columns(self) -> list[TableColumnSpec]:
        """Return the Phase 1 source-table column specification."""

        return [
            TableColumnSpec(key="ID", title="ID", width_hint=60, alignment="right"),
            TableColumnSpec(key="X", title="X", width_hint=90, alignment="right"),
            TableColumnSpec(key="Y", title="Y", width_hint=90, alignment="right"),
            TableColumnSpec(key="RA", title="RA", width_hint=130),
            TableColumnSpec(key="Dec", title="Dec", width_hint=130),
            TableColumnSpec(key="Flux", title="Flux", width_hint=110, alignment="right"),
            TableColumnSpec(key="Peak", title="Peak", width_hint=110, alignment="right"),
            TableColumnSpec(key="SNR", title="SNR", width_hint=80, alignment="right"),
            TableColumnSpec(key="NPix", title="NPix", width_hint=80, alignment="right"),
            TableColumnSpec(key="BkgRMS", title="BkgRMS", width_hint=95, alignment="right"),
            TableColumnSpec(key="A", title="A", width_hint=80, alignment="right"),
            TableColumnSpec(key="B", title="B", width_hint=80, alignment="right"),
            TableColumnSpec(key="Theta", title="Theta", width_hint=90, alignment="right"),
            TableColumnSpec(key="Flag", title="Flag", width_hint=70, alignment="right"),
        ]

    def configure_columns(self, columns: Sequence[TableColumnSpec]) -> None:
        """Install the source-table column specification."""

        self.columns = [
            TableColumnSpec(
                key=column.key,
                title=column.title,
                width_hint=column.width_hint,
                visible=True if column.key in self.MANDATORY_COLUMN_KEYS else column.visible,
                alignment=column.alignment,
            )
            for column in columns
        ]
        self.table_widget.setColumnCount(len(self.columns))
        self.table_widget.setHorizontalHeaderLabels([column.title for column in self.columns])
        for index, column in enumerate(self.columns):
            self.table_widget.setColumnHidden(index, not column.visible)
            self.table_widget.setColumnWidth(index, column.width_hint)
        if self.rows:
            self._render_rows()

    def populate(self, catalog: SourceCatalog) -> None:
        """Populate the table from a source catalog.

        Expected caller: `MainWindow.handle_roi_selected()`.
        """

        self.catalog = catalog
        self._update_detail_view()

    def populate_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        """Populate the table from pre-formatted row dictionaries."""

        view_models = [
            TableRowViewModel(row_index=index, values=dict(row))
            for index, row in enumerate(rows)
        ]
        self.set_row_view_models(view_models)

    def set_row_view_models(self, rows: Sequence[TableRowViewModel]) -> None:
        """Install row view models prepared by the coordinator layer."""

        self.rows = list(rows)
        self._render_rows()

    def row_view_models(self) -> list[TableRowViewModel]:
        """Return the currently cached row view models."""

        return list(self.rows)

    def set_view_state(self, state: TableViewState) -> None:
        """Apply structured table view state."""

        self.view_state = state
        self.selection_state = state.selection
        self._apply_view_state()

    def clear_catalog(self) -> None:
        """Clear the table contents and associated catalog."""

        self.catalog = None
        self.rows = []
        self.filtered_rows = []
        self.selection_state = TableSelectionState()
        self.view_state = TableViewState()
        self.table_widget.clearContents()
        self.table_widget.setRowCount(0)
        self.table_widget.clearSelection()
        self.detail_view.clear()
        self.clear_cutout_image()
        self._apply_view_state()

    def select_source(self, index: int) -> None:
        """Select a source row programmatically.

        Expected caller: `MainWindow.handle_source_clicked()` or future canvas-to-table sync.
        """

        if index < 0:
            return

        for row_index in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row_index, 0)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) == index:
                self.table_widget.selectRow(row_index)
                self.selection_state.selected_row = index
                self._update_detail_view(index)
                return

    def set_selection_state(self, state: TableSelectionState) -> None:
        """Apply structured selection state to the table."""

        self.selection_state = state
        if state.selected_row is not None:
            self.select_source(state.selected_row)

    def current_selection_state(self) -> TableSelectionState:
        """Return the current structured selection state."""

        return self.selection_state

    def set_feedback_state(self, state: ViewFeedbackState) -> None:
        """Apply a feedback state to the table view."""

        self.view_state.feedback = state
        self._apply_view_state()

    def filter_text(self) -> str:
        """Return the current free-text row filter."""

        return self.filter_input.text()

    def set_filter_text(self, text: str) -> None:
        """Programmatically update the row filter."""

        self.filter_input.setText(text)

    def _apply_view_state(self) -> None:
        """Refresh placeholder visibility from the current composite state."""

        feedback = self.view_state.feedback
        message = feedback.title or feedback.detail or "No Sources"
        if self.view_state.has_catalog and not self.filtered_rows and self.filter_input.text().strip():
            message = "No sources match the current filter."
        self.feedback_label.setText(message)
        show_feedback = (
            (feedback.visible and not self.view_state.has_catalog)
            or (self.view_state.has_catalog and not self.filtered_rows and bool(self.filter_input.text().strip()))
        )
        self.feedback_label.setVisible(show_feedback)
        self.filter_input.setVisible(self.view_state.has_catalog)
        self.summary_label.setVisible(self.view_state.has_catalog)
        self.table_widget.setVisible(True)
        if self.view_state.has_catalog:
            self.summary_label.setText(f"Showing {len(self.filtered_rows)} / {len(self.rows)} sources")
        else:
            self.summary_label.clear()
        self.detail_label.setVisible(self.view_state.has_catalog)
        self.detail_view.setVisible(self.view_state.has_catalog)
        self.cutout_label.setVisible(self.view_state.has_catalog)
        self.cutout_view.setVisible(self.view_state.has_catalog)

    def _emit_selection_changed(self) -> None:
        """Bridge table selection into the public source-clicked signal."""

        current_item = self.table_widget.currentItem()
        if current_item is None:
            return
        source_index = current_item.data(Qt.ItemDataRole.UserRole)
        if source_index is None:
            return
        self.selection_state.selected_row = int(source_index)
        self._update_detail_view(int(source_index))
        self.source_clicked.emit(int(source_index))

    def _handle_filter_changed(self, text: str) -> None:
        """Rebuild the visible rows when the free-text filter changes."""

        self._render_rows()
        self.filter_changed.emit(text)

    def _render_rows(self) -> None:
        """Render the current filtered row set into the table widget."""

        self.filtered_rows = self._filtered_row_models()
        sorting_enabled = self.table_widget.isSortingEnabled()
        self.table_widget.setSortingEnabled(False)
        self.table_widget.clearContents()
        self.table_widget.setRowCount(len(self.filtered_rows))
        for row_index, row_model in enumerate(self.filtered_rows):
            for column_index, column in enumerate(self.columns):
                value = row_model.values.get(column.key, "")
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, row_model.row_index)
                if column.alignment == "right":
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                self.table_widget.setItem(row_index, column_index, item)
        self.table_widget.setSortingEnabled(sorting_enabled)
        if self.selection_state.selected_row is not None:
            visible_indices = {row_model.row_index for row_model in self.filtered_rows}
            if self.selection_state.selected_row not in visible_indices:
                self.selection_state.selected_row = None
                self.table_widget.clearSelection()
                self._update_detail_view()
            else:
                self.select_source(self.selection_state.selected_row)
        self._apply_view_state()

    def _filtered_row_models(self) -> list[TableRowViewModel]:
        """Return the row models matching the current free-text filter."""

        query = self.filter_input.text().strip().lower()
        if not query:
            return list(self.rows)

        filtered: list[TableRowViewModel] = []
        for row_model in self.rows:
            for value in row_model.values.values():
                if query in str(value).lower():
                    filtered.append(row_model)
                    break
        return filtered

    def _update_detail_view(self, source_index: int | None = None) -> None:
        """Refresh the selected-source detail panel from the backing catalog."""

        if source_index is None:
            source_index = self.selection_state.selected_row

        if self.catalog is None or source_index is None:
            self.detail_view.setPlainText("")
            return

        record = self.catalog.get(source_index)
        if record is None:
            self.detail_view.setPlainText("")
            return

        lines = [
            f"ID: {record.source_id}",
            f"X: {record.x}",
            f"Y: {record.y}",
            f"RA: {record.ra}",
            f"Dec: {record.dec}",
            f"Flux: {record.flux}",
            f"Peak: {record.peak}",
            f"SNR: {record.snr}",
            f"NPix: {record.npix}",
            f"BkgRMS: {record.background_rms}",
            f"A: {record.a}",
            f"B: {record.b}",
            f"Theta: {record.theta}",
            f"Flag: {record.flag}",
        ]
        self.detail_view.setPlainText("\n".join(lines))

    def set_cutout_image(self, image: QImage | None) -> None:
        """Show a source-centered cutout preview below the detail fields."""

        if image is None or image.isNull():
            self.clear_cutout_image()
            return

        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.cutout_view.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.cutout_view.setPixmap(scaled)
        self.cutout_view.setText("")

    def clear_cutout_image(self) -> None:
        """Reset the cutout preview to its empty placeholder state."""

        self.cutout_view.clear()
        self.cutout_view.setText("Select a source\nto preview its cutout.")
