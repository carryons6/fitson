from __future__ import annotations

import html
import shlex
from typing import Any, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QKeySequence, QMouseEvent, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .contracts import TableColumnSpec, TableRowViewModel, TableSelectionState, TableViewState, ViewFeedbackState
from ..core.source_catalog import SourceCatalog


class _CutoutPreviewLabel(QLabel):
    """Cutout preview label that can request re-centering on double click."""

    double_clicked = Signal()
    resized = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class _TypedTableWidgetItem(QTableWidgetItem):
    """Table item that sorts using the original typed value when available."""

    def __init__(self, text: str, *, sort_key: tuple[int, Any]) -> None:
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        other_key = getattr(other, "_sort_key", (1, other.text().casefold()))
        return self._sort_key < other_key


class SourceTableDock(QDockWidget):
    """Dockable source-table skeleton.

    View contract:
    - Input from `MainWindow`: source catalog and selection changes.
    - Output to `MainWindow`: clicked row index.
    """

    source_clicked = Signal(int)
    source_hovered = Signal(int)
    filter_changed = Signal(str)
    cutout_mode_changed = Signal(str)
    MANDATORY_COLUMN_KEYS = ("ID", "X", "Y")
    CUTOUT_MODE_INTENSITY = "Intensity"
    CUTOUT_MODE_BACKGROUND = "Background"
    CUTOUT_MODE_RESIDUAL = "Residual"
    CUTOUT_MODE_CONNECTED_REGION = "Connected Region"
    CUTOUT_EMPTY_VIEW_STYLE = (
        "background-color: #0f172a; color: #eff6ff; border: 1px solid #60a5fa; "
        "border-radius: 8px; padding: 16px; font-size: 13px; font-weight: 600;"
    )
    CUTOUT_FILLED_VIEW_STYLE = "background: #101419; border: 1px solid #2e3b4a;"
    DETAIL_FIELDS = (
        ("ID", "source_id"),
        ("X", "x"),
        ("Y", "y"),
        ("RA", "ra"),
        ("Dec", "dec"),
        ("Flux", "flux"),
        ("Peak", "peak"),
        ("SNR", "snr"),
        ("NPix", "npix"),
        ("BkgRMS", "background_rms"),
        ("A", "a"),
        ("B", "b"),
        ("Theta", "theta"),
        ("Flag", "flag"),
    )

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.catalog: SourceCatalog | None = None
        self.columns: list[TableColumnSpec] = []
        self.rows: list[TableRowViewModel] = []
        self.filtered_rows: list[TableRowViewModel] = []
        self.selection_state = TableSelectionState()
        self.view_state = TableViewState()
        self._status_note_text = ""
        self._cutout_image: QImage | None = None
        self.content_widget = QWidget(self)
        self.layout = QVBoxLayout(self.content_widget)
        self.content_splitter = QSplitter(Qt.Orientation.Vertical, self.content_widget)
        self.inspector_tabs = QTabWidget(self.content_splitter)
        self.feedback_label = QLabel(self.tr("No Sources"), self.content_widget)
        self.filter_input = QLineEdit(self.content_widget)
        self.summary_label = QLabel("", self.content_widget)
        self.table_widget = QTableWidget(self.content_splitter)
        self.detail_panel = QWidget(self.inspector_tabs)
        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_table = QTableWidget(self.detail_panel)
        self.cutout_panel = QWidget(self.inspector_tabs)
        self.cutout_layout = QVBoxLayout(self.cutout_panel)
        self.cutout_header_widget = QWidget(self.cutout_panel)
        self.cutout_header_layout = QHBoxLayout(self.cutout_header_widget)
        self.cutout_mode_label = QLabel(self.tr("View:"), self.cutout_header_widget)
        self.cutout_mode_selector = QComboBox(self.cutout_header_widget)
        self.cutout_hint_label = QLabel(self.cutout_panel)
        self.cutout_view = _CutoutPreviewLabel(self.cutout_panel)

        self.setObjectName("source_table_dock")
        self.setWindowTitle(self.tr("Source Table"))
        self.setMinimumHeight(260)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(6)
        self.filter_input.setPlaceholderText(self.tr("Filter sources or use field:value"))
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSortingEnabled(True)
        self.table_widget.setMinimumHeight(180)
        self.table_widget.setMinimumWidth(320)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(6)
        self.detail_table.setColumnCount(2)
        self.detail_table.setHorizontalHeaderLabels([self.tr("Field"), self.tr("Value")])
        self.detail_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.detail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.detail_table.setWordWrap(False)
        self.detail_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.detail_table.setMinimumHeight(160)
        self.cutout_layout.setContentsMargins(0, 0, 0, 0)
        self.cutout_layout.setSpacing(6)
        self.inspector_tabs.setDocumentMode(True)
        self.inspector_tabs.addTab(self.detail_panel, self.tr("Details"))
        self.inspector_tabs.addTab(self.cutout_panel, self.tr("Cutout"))
        self.inspector_tabs.setTabToolTip(0, self.tr("Selected source fields and metrics."))
        self.inspector_tabs.setTabToolTip(1, self.tr("Source cutout preview and view mode."))
        self.cutout_header_layout.setContentsMargins(0, 0, 0, 0)
        self.cutout_header_layout.addWidget(self.cutout_mode_label)
        self._populate_cutout_mode_selector()
        self.cutout_header_layout.addWidget(self.cutout_mode_selector)
        self.cutout_header_layout.addStretch(1)
        self.cutout_hint_label.setWordWrap(True)
        self.cutout_hint_label.setText(
            self.tr("Double-click the cutout to recenter the selected source.")
        )
        self.cutout_hint_label.setStyleSheet(
            "background-color: #dbeafe; color: #102a43; border: 1px solid #93c5fd; "
            "border-radius: 4px; padding: 6px 8px; font-size: 12px;"
        )
        self.cutout_view.setMinimumSize(120, 120)
        self.cutout_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cutout_view.setWordWrap(True)
        self.cutout_view.setStyleSheet(self.CUTOUT_EMPTY_VIEW_STYLE)
        self.cutout_view.setTextFormat(Qt.TextFormat.RichText)
        self.cutout_view.setText(self._cutout_placeholder_html())
        self.cutout_view.setToolTip("")
        self.layout.addWidget(self.feedback_label)
        self.layout.addWidget(self.filter_input)
        self.layout.addWidget(self.summary_label)
        self.layout.addWidget(self.content_splitter, 1)
        self.detail_layout.addWidget(self.detail_table, 1)
        self.cutout_layout.addWidget(self.cutout_header_widget)
        self.cutout_layout.addWidget(self.cutout_hint_label)
        self.cutout_layout.addWidget(self.cutout_view, 1)
        self.content_splitter.addWidget(self.table_widget)
        self.content_splitter.addWidget(self.inspector_tabs)
        self.setWidget(self.content_widget)
        self.configure_columns(self.default_columns())
        self.table_widget.itemSelectionChanged.connect(self._emit_selection_changed)
        self.table_widget.itemPressed.connect(self._handle_item_pressed)
        self.table_widget.setMouseTracking(True)
        self.table_widget.viewport().setMouseTracking(True)
        self.table_widget.itemEntered.connect(self._emit_hover_from_item)
        self._recenter_shortcut_return = QShortcut(QKeySequence(Qt.Key.Key_Return), self.table_widget)
        self._recenter_shortcut_enter = QShortcut(QKeySequence(Qt.Key.Key_Enter), self.table_widget)
        self._recenter_shortcut_return.activated.connect(self._reemit_current_selection)
        self._recenter_shortcut_enter.activated.connect(self._reemit_current_selection)
        self.cutout_view.double_clicked.connect(self._reemit_current_selection)
        self.cutout_view.resized.connect(self._refresh_cutout_pixmap)
        self.inspector_tabs.currentChanged.connect(self._handle_inspector_tab_changed)
        self.dockLocationChanged.connect(self.update_layout_for_dock_area)
        self.filter_input.textChanged.connect(self._handle_filter_changed)
        self.cutout_mode_selector.currentIndexChanged.connect(self._emit_cutout_mode_changed)
        self.show_cutout_tab()
        self.update_layout_for_dock_area(Qt.DockWidgetArea.RightDockWidgetArea)
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
        self.table_widget.setHorizontalHeaderLabels([self.tr(column.title) for column in self.columns])
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
        self._status_note_text = ""
        self.table_widget.clearContents()
        self.table_widget.setRowCount(0)
        self.table_widget.clearSelection()
        self.detail_table.clearContents()
        self.detail_table.setRowCount(0)
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

    def set_status_note(self, text: str) -> None:
        """Show supplemental table status such as stale-result warnings."""

        self._status_note_text = text.strip()
        self._apply_view_state()

    def _apply_view_state(self) -> None:
        """Refresh placeholder visibility from the current composite state."""

        feedback = self.view_state.feedback
        message = feedback.title or feedback.detail or self.tr("No Sources")
        if self.view_state.has_catalog and not self.filtered_rows and self.filter_input.text().strip():
            message = self.tr("No sources match the current filter.")
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
            summary = self.tr("Showing {shown} / {total} sources").format(
                shown=len(self.filtered_rows),
                total=len(self.rows),
            )
            if self._status_note_text:
                summary = f"{summary} | {self._status_note_text}"
            self.summary_label.setText(summary)
        else:
            self.summary_label.clear()
        self.inspector_tabs.setVisible(self.view_state.has_catalog)

    def _emit_cutout_mode_changed(self, _index: int) -> None:
        self.cutout_mode_changed.emit(self.current_cutout_mode())

    def _emit_hover_from_item(self, item: QTableWidgetItem) -> None:
        """Emit a hover signal carrying the source index of the entered row."""

        source_index = self._source_index_from_item(item)
        if source_index is None:
            return
        self.source_hovered.emit(source_index)

    def _emit_selection_changed(self) -> None:
        """Bridge table selection into the public source-clicked signal."""

        source_index = self._source_index_from_item(self.table_widget.currentItem())
        if source_index is None:
            return
        self.selection_state.selected_row = source_index
        self._update_detail_view(source_index)
        self.source_clicked.emit(source_index)

    def _handle_item_pressed(self, item: QTableWidgetItem) -> None:
        """Re-emit clicks on the already-selected row so the caller can re-center."""

        source_index = self._source_index_from_item(item)
        if source_index is None:
            return
        if self.selection_state.selected_row != source_index:
            return
        self._update_detail_view(source_index)
        self.source_clicked.emit(source_index)

    def _reemit_current_selection(self) -> None:
        """Emit the current selection again for explicit re-centering actions."""

        source_index = self.selection_state.selected_row
        if source_index is None:
            source_index = self._source_index_from_item(self.table_widget.currentItem())
        if source_index is None:
            return
        self.selection_state.selected_row = source_index
        self._update_detail_view(source_index)
        self.source_clicked.emit(source_index)

    def _source_index_from_item(self, item: QTableWidgetItem | None) -> int | None:
        """Resolve the backing source index for a rendered table item."""

        if item is None:
            return None
        row_item = self.table_widget.item(item.row(), 0)
        if row_item is None:
            return None
        source_index = row_item.data(Qt.ItemDataRole.UserRole)
        if source_index is None:
            return None
        return int(source_index)

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
                item = _TypedTableWidgetItem(
                    str(value),
                    sort_key=self._sort_key_for_value(value),
                )
                item.setData(Qt.ItemDataRole.UserRole, row_model.row_index)
                if column.alignment == "right":
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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

    def _handle_inspector_tab_changed(self, _index: int) -> None:
        """Refresh cutout rendering when its tab becomes visible."""

        if self.inspector_tabs.currentWidget() is self.cutout_panel:
            self._refresh_cutout_pixmap()

    def show_cutout_tab(self) -> None:
        """Switch the inspector to the cutout preview tab."""

        self.inspector_tabs.setCurrentWidget(self.cutout_panel)

    def update_layout_for_dock_area(self, area: Qt.DockWidgetArea) -> None:
        """Adapt the internal splitter to side-vs-bottom docking constraints."""

        side_dock = area in (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        orientation = Qt.Orientation.Vertical if side_dock else Qt.Orientation.Horizontal
        if self.content_splitter.orientation() != orientation:
            self.content_splitter.setOrientation(orientation)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setStretchFactor(0, 5 if side_dock else 4)
        self.content_splitter.setStretchFactor(1, 3 if side_dock else 2)
        if side_dock:
            self.table_widget.setMinimumWidth(320)
            self.table_widget.setMinimumHeight(180)
            self.inspector_tabs.setMinimumWidth(0)
            self.inspector_tabs.setMinimumHeight(240)
            self.cutout_view.setMinimumSize(140, 140)
            self.content_splitter.setSizes([560, 320])
        else:
            self.table_widget.setMinimumWidth(420)
            self.table_widget.setMinimumHeight(160)
            self.inspector_tabs.setMinimumWidth(300)
            self.inspector_tabs.setMinimumHeight(0)
            self.cutout_view.setMinimumSize(120, 120)
            self.content_splitter.setSizes([760, 360])
        self._refresh_cutout_pixmap()

    def _filtered_row_models(self) -> list[TableRowViewModel]:
        """Return the row models matching the current free-text filter."""

        query = self.filter_input.text().strip()
        if not query:
            return list(self.rows)

        tokens = self._parse_filter_tokens(query)
        filtered: list[TableRowViewModel] = []
        for row_model in self.rows:
            if self._row_matches_filter_tokens(row_model, tokens):
                filtered.append(row_model)
        return filtered

    def _parse_filter_tokens(self, query: str) -> list[tuple[str, str, str]]:
        """Split a free-text query into general or column-specific filter tokens."""

        try:
            raw_tokens = shlex.split(query)
        except ValueError:
            raw_tokens = query.split()

        tokens: list[tuple[str, str, str]] = []
        for token in raw_tokens:
            field_name, sep, value = token.partition(":")
            if sep:
                resolved_key = self._resolve_filter_field_key(field_name)
                if resolved_key is not None:
                    tokens.append(("field", resolved_key, value.casefold()))
                    continue
            tokens.append(("general", "", token.casefold()))
        return tokens

    def _resolve_filter_field_key(self, field_name: str) -> str | None:
        """Map a query field alias such as `flux` or `bkg_rms` to a column key."""

        normalized = self._normalize_filter_field_name(field_name)
        if not normalized:
            return None

        for column in self.columns:
            aliases = {
                self._normalize_filter_field_name(column.key),
                self._normalize_filter_field_name(column.title),
            }
            if normalized in aliases:
                return column.key
        return None

    @staticmethod
    def _normalize_filter_field_name(text: str) -> str:
        """Normalize field aliases so filter keys can ignore spaces and punctuation."""

        return "".join(ch for ch in text.casefold() if ch.isalnum())

    def _row_matches_filter_tokens(
        self,
        row_model: TableRowViewModel,
        tokens: list[tuple[str, str, str]],
    ) -> bool:
        """Return whether a row satisfies all active filter tokens."""

        for token_kind, field_key, query in tokens:
            if token_kind == "field":
                value = row_model.values.get(field_key, "")
                if query not in str(value).casefold():
                    return False
                continue

            if not any(query in str(value).casefold() for value in row_model.values.values()):
                return False
        return True

    @staticmethod
    def _sort_key_for_value(value: Any) -> tuple[int, Any]:
        """Build a stable sort key that keeps numeric values in numeric order."""

        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, float(value))
        text = str(value).strip()
        if not text or text == "-":
            return (2, "")
        try:
            return (0, float(text))
        except ValueError:
            return (1, text.casefold())

    def _update_detail_view(self, source_index: int | None = None) -> None:
        """Refresh the selected-source detail panel from the backing catalog."""

        if source_index is None:
            source_index = self.selection_state.selected_row

        if self.catalog is None or source_index is None:
            self.detail_table.clearContents()
            self.detail_table.setRowCount(0)
            return

        record = self.catalog.get(source_index)
        if record is None:
            self.detail_table.clearContents()
            self.detail_table.setRowCount(0)
            return

        self.detail_table.clearContents()
        self.detail_table.setRowCount(len(self.DETAIL_FIELDS))
        for row_index, (label, attr_name) in enumerate(self.DETAIL_FIELDS):
            label_item = QTableWidgetItem(self.tr(label))
            value_item = QTableWidgetItem(str(getattr(record, attr_name)))
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.detail_table.setItem(row_index, 0, label_item)
            self.detail_table.setItem(row_index, 1, value_item)
        self.detail_table.resizeRowsToContents()

    def set_cutout_image(self, image: QImage | None) -> None:
        """Show a source-centered cutout preview below the detail fields."""

        if image is None or image.isNull():
            self.clear_cutout_image()
            return

        self._cutout_image = image.copy()
        self._refresh_cutout_pixmap()

    def _refresh_cutout_pixmap(self) -> None:
        """Rescale the cached cutout to fit the current preview pane."""

        if self._cutout_image is None or self._cutout_image.isNull():
            return

        preview_size = self.cutout_view.size()
        if preview_size.width() <= 1 or preview_size.height() <= 1:
            return

        pixmap = QPixmap.fromImage(self._cutout_image)
        scaled = pixmap.scaled(
            preview_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.cutout_view.setStyleSheet(self.CUTOUT_FILLED_VIEW_STYLE)
        self.cutout_view.setPixmap(scaled)
        self.cutout_view.setText("")

    def current_cutout_mode(self) -> str:
        """Return the selected cutout review mode."""

        mode = self.cutout_mode_selector.currentData()
        if isinstance(mode, str) and mode:
            return mode
        return self.CUTOUT_MODE_INTENSITY

    def clear_cutout_image(self, message: str | None = None) -> None:
        """Reset the cutout preview to its empty placeholder state."""

        self._cutout_image = None
        self.cutout_view.clear()
        self.cutout_view.setStyleSheet(self.CUTOUT_EMPTY_VIEW_STYLE)
        self.cutout_view.setText(self._cutout_placeholder_html(message))

    def _populate_cutout_mode_selector(self) -> None:
        current_mode = self.current_cutout_mode()
        self.cutout_mode_selector.blockSignals(True)
        self.cutout_mode_selector.clear()
        for mode in (
            self.CUTOUT_MODE_INTENSITY,
            self.CUTOUT_MODE_BACKGROUND,
            self.CUTOUT_MODE_RESIDUAL,
            self.CUTOUT_MODE_CONNECTED_REGION,
        ):
            self.cutout_mode_selector.addItem(self.tr(mode), mode)
        index = self.cutout_mode_selector.findData(current_mode)
        self.cutout_mode_selector.setCurrentIndex(max(index, 0))
        self.cutout_mode_selector.blockSignals(False)

    def _cutout_placeholder_html(self, message: str | None = None) -> str:
        """Return the rich-text placeholder shown when no cutout preview is available."""

        if message is None or not message.strip():
            title = self.tr("No source selected")
            detail = self.tr("Choose a row to preview its cutout.")
        else:
            title = message.strip()
            detail = ""

        title_html = html.escape(title)
        if detail:
            detail_html = html.escape(detail)
            return (
                "<div style='text-align:center;'>"
                f"<div style='font-size:15px; font-weight:700; margin-bottom:6px;'>{title_html}</div>"
                f"<div style='font-size:12px; font-weight:500; color:#bfdbfe;'>{detail_html}</div>"
                "</div>"
            )
        return (
            "<div style='text-align:center;'>"
            f"<div style='font-size:14px; font-weight:700;'>{title_html}</div>"
            "</div>"
        )
