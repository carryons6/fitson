from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QLabel,
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

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.catalog: SourceCatalog | None = None
        self.columns: list[TableColumnSpec] = []
        self.rows: list[TableRowViewModel] = []
        self.selection_state = TableSelectionState()
        self.view_state = TableViewState()
        self.content_widget = QWidget(self)
        self.layout = QVBoxLayout(self.content_widget)
        self.feedback_label = QLabel("No Sources", self.content_widget)
        self.table_widget = QTableWidget(self.content_widget)

        self.setObjectName("source_table_dock")
        self.setWindowTitle("Source Table")
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True)
        self.layout.addWidget(self.feedback_label)
        self.layout.addWidget(self.table_widget)
        self.setWidget(self.content_widget)
        self.configure_columns(self.default_columns())
        self.table_widget.itemSelectionChanged.connect(self._emit_selection_changed)
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
            TableColumnSpec(key="A", title="A", width_hint=80, alignment="right"),
            TableColumnSpec(key="B", title="B", width_hint=80, alignment="right"),
            TableColumnSpec(key="Theta", title="Theta", width_hint=90, alignment="right"),
            TableColumnSpec(key="Flag", title="Flag", width_hint=70, alignment="right"),
        ]

    def configure_columns(self, columns: Sequence[TableColumnSpec]) -> None:
        """Install the source-table column specification."""

        self.columns = list(columns)
        self.table_widget.setColumnCount(len(self.columns))
        self.table_widget.setHorizontalHeaderLabels([column.title for column in self.columns])
        for index, column in enumerate(self.columns):
            self.table_widget.setColumnHidden(index, not column.visible)
            self.table_widget.setColumnWidth(index, column.width_hint)

    def populate(self, catalog: SourceCatalog) -> None:
        """Populate the table from a source catalog.

        Expected caller: `MainWindow.handle_roi_selected()`.
        """

        self.catalog = catalog

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
        self.table_widget.setRowCount(len(self.rows))
        for row_index, row_model in enumerate(self.rows):
            for column_index, column in enumerate(self.columns):
                value = row_model.values.get(column.key, "")
                item = QTableWidgetItem(str(value))
                if column.alignment == "right":
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                self.table_widget.setItem(row_index, column_index, item)

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
        self.selection_state = TableSelectionState()
        self.view_state = TableViewState()
        self.table_widget.clearContents()
        self.table_widget.setRowCount(0)
        self._apply_view_state()

    def select_source(self, index: int) -> None:
        """Select a source row programmatically.

        Expected caller: `MainWindow.handle_source_clicked()` or future canvas-to-table sync.
        """

        if 0 <= index < self.table_widget.rowCount():
            self.table_widget.selectRow(index)
            self.selection_state.selected_row = index

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

    def _apply_view_state(self) -> None:
        """Refresh placeholder visibility from the current composite state."""

        feedback = self.view_state.feedback
        message = feedback.title or feedback.detail or "No Sources"
        self.feedback_label.setText(message)
        show_feedback = feedback.visible and not self.view_state.has_catalog
        self.feedback_label.setVisible(show_feedback)
        self.table_widget.setVisible(True)

    def _emit_selection_changed(self) -> None:
        """Bridge table selection into the public source-clicked signal."""

        current_row = self.table_widget.currentRow()
        if current_row < 0:
            return
        self.selection_state.selected_row = current_row
        self.source_clicked.emit(current_row)
