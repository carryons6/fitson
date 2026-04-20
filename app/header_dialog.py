from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, QSettings, QSignalBlocker, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QGuiApplication, QPalette, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
)

from .contracts import HeaderCard, HeaderFilterState, HeaderPayload, HeaderViewState, ViewFeedbackState
from .fits_keyword_docs import describe_keyword
from .header_parser import parse_header_text


CARD_ROLE = int(Qt.ItemDataRole.UserRole) + 1
HEADER_DIALOG_SETTINGS_GROUP = "header_dialog"
DEFAULT_COLUMN_WIDTHS = (72, 240, 360, 260)
VIEW_MODE_STRUCTURED = "structured"
VIEW_MODE_RAW = "raw"


def _normalized_header_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text else 0


def _card_matches(card: HeaderCard, state: HeaderFilterState) -> bool:
    query = state.query
    if not query:
        return False

    scope = state.scope if state.scope in {"any", "key", "value", "comment"} else "any"
    if scope == "key":
        fields = (card.key,)
    elif scope == "value":
        fields = (card.value,)
    elif scope == "comment":
        fields = (card.comment,)
    else:
        fields = (card.key, card.value, card.comment)

    if state.use_regex:
        flags = 0 if state.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error:
            return False
        return any(bool(pattern.search(field)) for field in fields)

    if state.case_sensitive:
        return any(query in field for field in fields)
    lowered_query = query.lower()
    return any(lowered_query in field.lower() for field in fields)


def _copy_text(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


class HeaderTableModel(QAbstractTableModel):
    """Read-only table model for structured FITS header cards."""

    _HEADERS = ("#", "Key", "Value", "Comment")

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._payload: HeaderPayload | None = None

    def set_payload(self, payload: HeaderPayload | None) -> None:
        self.beginResetModel()
        self._payload = payload
        self.endResetModel()

    def payload(self) -> HeaderPayload | None:
        return self._payload

    def card_at(self, row: int) -> HeaderCard | None:
        payload = self._payload
        if payload is None or not (0 <= row < len(payload.cards)):
            return None
        return payload.cards[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._payload is None:
            return 0
        return len(self._payload.cards)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._HEADERS):
            return self.tr(self._HEADERS[section])
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        card = self.card_at(index.row())
        if card is None:
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return str(card.index)
            if index.column() == 1:
                return card.key
            if index.column() == 2:
                return card.value
            if index.column() == 3:
                return card.comment
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() == 0:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background_for_kind(card.kind)

        if role == Qt.ItemDataRole.FontRole:
            return self._font_for_kind(card.kind)

        if role == Qt.ItemDataRole.ForegroundRole and card.kind == "blank":
            color = QColor(QApplication.palette().color(QPalette.ColorRole.Text))
            color.setAlpha(100)
            return color

        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 1:
            description = describe_keyword(card.key)
            if description:
                return self.tr(description)

        if role == CARD_ROLE:
            return card

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def _background_for_kind(self, kind: str) -> QColor | None:
        palette = QApplication.palette()
        if kind == "blank":
            return None

        if kind == "comment":
            color = QColor(palette.color(QPalette.ColorRole.AlternateBase))
            color.setAlpha(160)
            return color

        if kind == "history":
            color = QColor(palette.color(QPalette.ColorRole.Link))
            color.setAlpha(28)
            return color

        if kind == "hierarch":
            color = QColor(palette.color(QPalette.ColorRole.Button))
            color.setAlpha(150)
            return color

        if kind == "continue":
            color = QColor(palette.color(QPalette.ColorRole.Highlight))
            color.setAlpha(34)
            return color

        return None

    def _font_for_kind(self, kind: str) -> QFont | None:
        font = QApplication.font()
        if kind in {"comment", "history"}:
            font.setItalic(True)
            return font
        if kind == "hierarch":
            font.setBold(True)
            return font
        return None


class HeaderFilterProxyModel(QSortFilterProxyModel):
    """Proxy model that filters structured header cards by scope and regex options."""

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._filter_state = HeaderFilterState()

    def set_filter_state(self, state: HeaderFilterState) -> None:
        self._filter_state = replace(state)
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        del source_parent
        query = self._filter_state.query
        if not query:
            return True
        model = self.sourceModel()
        if not isinstance(model, HeaderTableModel):
            return True
        card = model.card_at(source_row)
        if card is None:
            return False
        return _card_matches(card, self._filter_state)


class HeaderDialog(QDialog):
    """Structured FITS header viewer with per-HDU selection and raw fallback."""

    def __init__(self, parent: Any | None = None, *, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self._settings = settings or QSettings("AstroView", "AstroView")
        self._payloads: list[HeaderPayload] = []
        self._match_cards: list[HeaderCard] = []
        self._context_card: HeaderCard | None = None

        self.header_text = ""
        self.filter_state = HeaderFilterState()
        self.view_state = HeaderViewState()

        self.layout = QVBoxLayout(self)
        self.header_controls_layout = QHBoxLayout()
        self.filter_layout = QHBoxLayout()
        self.status_layout = QHBoxLayout()

        self.hdu_label = QLabel(self.tr("HDU:"), self)
        self.hdu_combo = QComboBox(self)
        self.view_label = QLabel(self.tr("View:"), self)
        self.view_selector = QComboBox(self)
        self.feedback_label = QLabel(self.tr("No Header"), self)
        self.filter_input = QLineEdit(self)
        self.scope_label = QLabel(self.tr("Scope:"), self)
        self.scope_combo = QComboBox(self)
        self.case_sensitive_checkbox = QCheckBox(self.tr("Case sensitive"), self)
        self.regex_checkbox = QCheckBox(self.tr("Regex"), self)
        self.prev_button = QPushButton(self.tr("Previous"), self)
        self.next_button = QPushButton(self.tr("Next"), self)
        self.result_label = QLabel(self)
        self.line_count_label = QLabel(self)
        self.stack = QStackedWidget(self)
        self.table_view = QTableView(self)
        self.raw_view = QPlainTextEdit(self)
        self.text_view = self.raw_view

        self.table_model = HeaderTableModel(self)
        self.proxy_model = HeaderFilterProxyModel(self)

        self.setObjectName("header_dialog")
        self.setWindowTitle(self.tr("FITS Header"))
        self.resize(1120, 760)

        self._build_controls()
        self._build_views()
        self._restore_preferences()
        self._connect_signals()
        self._apply_filter(reset_current_match=True)
        self._apply_view_state()

    def set_header_text(self, text: str) -> None:
        """Load one raw header into the dialog for compatibility with older callers."""

        normalized = _normalized_header_text(text)
        payload = HeaderPayload(
            hdu_index=0,
            name="HDU 0",
            kind="Header",
            shape=None,
            cards=parse_header_text(normalized),
            raw_text=normalized,
        )
        self.set_header_payloads([payload] if normalized else [])

    def set_header_payloads(self, payloads: list[HeaderPayload], current_hdu_index: int | None = None) -> None:
        """Load one or more HDU headers into the dialog."""

        normalized_payloads = [self._normalized_payload(payload) for payload in payloads]
        self._payloads = [payload for payload in normalized_payloads if payload.raw_text or payload.cards]
        self.view_state.available_hdus = [
            (payload.hdu_index, self._format_hdu_label(payload)) for payload in self._payloads
        ]

        with QSignalBlocker(self.hdu_combo):
            self.hdu_combo.clear()
            for payload in self._payloads:
                self.hdu_combo.addItem(self._format_hdu_label(payload), payload.hdu_index)

        if not self._payloads:
            self.clear()
            self.view_state.feedback = ViewFeedbackState(
                status="empty",
                title=self.tr("No Header"),
                detail=self.tr("Open a FITS file before viewing header cards."),
                visible=True,
            )
            self._apply_view_state()
            return

        target_hdu_index = self._resolve_hdu_index(current_hdu_index)
        self.view_state.feedback = ViewFeedbackState(status="ready")
        self._show_payload(target_hdu_index, reset_current_match=True)

    def set_filter_text(self, text: str) -> None:
        """Update the current filter string."""

        if self.filter_input.text() != text:
            self.filter_input.setText(text)
            return
        self.filter_state.query = text
        self.apply_filter()

    def set_filter_scope(self, scope: str) -> None:
        """Update the scope used for search matching."""

        index = self.scope_combo.findData(scope)
        if index >= 0 and self.scope_combo.currentIndex() != index:
            self.scope_combo.setCurrentIndex(index)
            return
        self.filter_state.scope = scope
        self.apply_filter()

    def set_case_sensitive(self, checked: bool) -> None:
        """Update whether header filtering should respect case."""

        if self.case_sensitive_checkbox.isChecked() != checked:
            self.case_sensitive_checkbox.setChecked(checked)
            return
        self.filter_state.case_sensitive = bool(checked)
        self.apply_filter()

    def set_use_regex(self, checked: bool) -> None:
        """Update whether the current query should be treated as a regex."""

        if self.regex_checkbox.isChecked() != checked:
            self.regex_checkbox.setChecked(checked)
            return
        self.filter_state.use_regex = bool(checked)
        self.apply_filter()

    def set_filter_state(self, state: HeaderFilterState) -> None:
        """Apply structured filter state to the header view."""

        self.filter_state = replace(state)
        with QSignalBlocker(self.filter_input):
            self.filter_input.setText(state.query)
        with QSignalBlocker(self.scope_combo):
            index = self.scope_combo.findData(state.scope)
            self.scope_combo.setCurrentIndex(max(0, index))
        with QSignalBlocker(self.case_sensitive_checkbox):
            self.case_sensitive_checkbox.setChecked(state.case_sensitive)
        with QSignalBlocker(self.regex_checkbox):
            self.regex_checkbox.setChecked(state.use_regex)
        self._store_preferences()
        self._apply_filter(reset_current_match=state.current_match <= 0)

    def current_filter_state(self) -> HeaderFilterState:
        """Return the current structured filter state."""

        return replace(self.filter_state)

    def set_view_state(self, state: HeaderViewState) -> None:
        """Apply structured view state to the header dialog."""

        feedback = state.feedback
        self.view_state.feedback = feedback
        self.view_state.view_mode = state.view_mode if state.view_mode in {VIEW_MODE_STRUCTURED, VIEW_MODE_RAW} else VIEW_MODE_STRUCTURED
        self.view_state.hdu_index = state.hdu_index
        self.view_state.available_hdus = list(state.available_hdus)

        with QSignalBlocker(self.view_selector):
            view_index = self.view_selector.findData(self.view_state.view_mode)
            self.view_selector.setCurrentIndex(max(0, view_index))
        self.stack.setCurrentIndex(0 if self.view_state.view_mode == VIEW_MODE_STRUCTURED else 1)

        if self._payloads:
            self._show_payload(self._resolve_hdu_index(self.view_state.hdu_index), reset_current_match=False)
        else:
            self.view_state.has_header = state.has_header
            self.view_state.line_count = state.line_count
            self._apply_view_state()
        self._store_preferences()

    def current_view_state(self) -> HeaderViewState:
        """Return the current composite header view state."""

        return HeaderViewState(
            has_header=self.view_state.has_header,
            hdu_index=self.view_state.hdu_index,
            available_hdus=list(self.view_state.available_hdus),
            view_mode=self.view_state.view_mode,
            line_count=self.view_state.line_count,
            feedback=self.view_state.feedback,
        )

    def apply_filter(self) -> None:
        """Apply the current search filter to the header view."""

        self._apply_filter(reset_current_match=True)

    def show_previous_match(self) -> None:
        """Select the previous structured/raw match and wrap at the beginning."""

        total = self.filter_state.match_count
        if total <= 0:
            return
        current = self.filter_state.current_match - 1
        self.filter_state.current_match = total if current < 1 else current
        self._store_preferences()
        self._sync_match_selection()

    def show_next_match(self) -> None:
        """Select the next structured/raw match and wrap at the end."""

        total = self.filter_state.match_count
        if total <= 0:
            return
        current = self.filter_state.current_match + 1
        self.filter_state.current_match = 1 if current > total else current
        self._store_preferences()
        self._sync_match_selection()

    def copy_selected_key(self) -> None:
        """Copy the selected card key to the clipboard."""

        card = self._selected_card()
        if card is not None:
            _copy_text(card.key)

    def copy_selected_value(self) -> None:
        """Copy the selected card value to the clipboard."""

        card = self._selected_card()
        if card is not None:
            _copy_text(card.value)

    def copy_selected_card(self) -> None:
        """Copy the raw card text for the selected structured row."""

        card = self._selected_card()
        if card is not None:
            _copy_text(card.raw_text or self._format_card_text(card))

    def copy_all_matching(self) -> None:
        """Copy every currently matched card, or the full payload when no filter is active."""

        payload = self._current_payload()
        if payload is None:
            return
        cards = self._match_cards if self.filter_state.query and self._match_cards else payload.cards
        _copy_text("\n".join(card.raw_text or self._format_card_text(card) for card in cards))

    def clear(self) -> None:
        """Clear header content while preserving search controls and persisted options."""

        self._payloads = []
        self._match_cards = []
        self._context_card = None
        self.header_text = ""
        self.filter_state.match_count = 0
        self.filter_state.current_match = 0
        self.view_state.has_header = False
        self.view_state.hdu_index = 0
        self.view_state.available_hdus = []
        self.view_state.line_count = 0

        with QSignalBlocker(self.hdu_combo):
            self.hdu_combo.clear()

        self.table_model.set_payload(None)
        self.raw_view.clear()
        self.proxy_model.set_filter_state(self.filter_state)
        self.table_view.clearSelection()
        self.raw_view.setExtraSelections([])
        self.result_label.clear()
        self.line_count_label.clear()
        self._update_navigation_buttons()
        self._apply_view_state()

    def set_feedback_state(self, state: ViewFeedbackState) -> None:
        """Apply a feedback state to the header dialog."""

        self.view_state.feedback = state
        self._apply_view_state()

    def hideEvent(self, event) -> None:
        self._store_preferences()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._store_preferences()
        super().closeEvent(event)

    def _build_controls(self) -> None:
        self.filter_input.setPlaceholderText(self.tr("Search header cards"))
        self.result_label.setMinimumWidth(160)
        self.line_count_label.setMinimumWidth(110)
        self.feedback_label.setWordWrap(True)

        self.view_selector.addItem(self.tr("Structured"), VIEW_MODE_STRUCTURED)
        self.view_selector.addItem(self.tr("Raw"), VIEW_MODE_RAW)

        self.scope_combo.addItem(self.tr("Any"), "any")
        self.scope_combo.addItem(self.tr("Key"), "key")
        self.scope_combo.addItem(self.tr("Value"), "value")
        self.scope_combo.addItem(self.tr("Comment"), "comment")

        self.header_controls_layout.addWidget(self.hdu_label)
        self.header_controls_layout.addWidget(self.hdu_combo, 1)
        self.header_controls_layout.addWidget(self.view_label)
        self.header_controls_layout.addWidget(self.view_selector)

        self.filter_layout.addWidget(self.filter_input, 1)
        self.filter_layout.addWidget(self.scope_label)
        self.filter_layout.addWidget(self.scope_combo)
        self.filter_layout.addWidget(self.case_sensitive_checkbox)
        self.filter_layout.addWidget(self.regex_checkbox)
        self.filter_layout.addWidget(self.prev_button)
        self.filter_layout.addWidget(self.next_button)

        self.status_layout.addWidget(self.result_label)
        self.status_layout.addWidget(self.line_count_label)
        self.status_layout.addStretch()

        self.layout.addLayout(self.header_controls_layout)
        self.layout.addLayout(self.filter_layout)
        self.layout.addLayout(self.status_layout)

    def _build_views(self) -> None:
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        self.proxy_model.setSourceModel(self.table_model)

        self.table_view.setModel(self.proxy_model)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.table_view.setFont(fixed_font)

        self.raw_view.setFont(fixed_font)
        self.raw_view.setReadOnly(True)
        self.raw_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw_view.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.raw_view.setTabStopDistance(4 * self.raw_view.fontMetrics().horizontalAdvance(" "))

        self.stack.addWidget(self.table_view)
        self.stack.addWidget(self.raw_view)
        self.layout.addWidget(self.stack, 1)
        self.layout.addWidget(self.feedback_label)

        for column, width in enumerate(DEFAULT_COLUMN_WIDTHS):
            self.table_view.setColumnWidth(column, width)

    def _connect_signals(self) -> None:
        self.filter_input.textChanged.connect(self._handle_filter_text_changed)
        self.scope_combo.currentIndexChanged.connect(self._handle_scope_changed)
        self.case_sensitive_checkbox.toggled.connect(self._handle_case_sensitive_changed)
        self.regex_checkbox.toggled.connect(self._handle_regex_changed)
        self.prev_button.clicked.connect(self.show_previous_match)
        self.next_button.clicked.connect(self.show_next_match)
        self.hdu_combo.currentIndexChanged.connect(self._handle_hdu_changed)
        self.view_selector.currentIndexChanged.connect(self._handle_view_mode_changed)
        self.table_view.doubleClicked.connect(self._handle_table_double_clicked)
        self.table_view.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table_view.horizontalHeader().sectionResized.connect(self._handle_section_resized)

    def _restore_preferences(self) -> None:
        scope = str(self._settings.value(f"{HEADER_DIALOG_SETTINGS_GROUP}/filter/scope", "any"))
        case_sensitive = self._settings.value(
            f"{HEADER_DIALOG_SETTINGS_GROUP}/filter/case_sensitive", False, type=bool
        )
        use_regex = self._settings.value(f"{HEADER_DIALOG_SETTINGS_GROUP}/filter/use_regex", False, type=bool)
        view_mode = str(self._settings.value(f"{HEADER_DIALOG_SETTINGS_GROUP}/view_mode", VIEW_MODE_STRUCTURED))

        if scope not in {"any", "key", "value", "comment"}:
            scope = "any"
        if view_mode not in {VIEW_MODE_STRUCTURED, VIEW_MODE_RAW}:
            view_mode = VIEW_MODE_STRUCTURED

        self.filter_state.scope = scope
        self.filter_state.case_sensitive = bool(case_sensitive)
        self.filter_state.use_regex = bool(use_regex)
        self.view_state.view_mode = view_mode

        with QSignalBlocker(self.scope_combo):
            self.scope_combo.setCurrentIndex(max(0, self.scope_combo.findData(scope)))
        with QSignalBlocker(self.case_sensitive_checkbox):
            self.case_sensitive_checkbox.setChecked(self.filter_state.case_sensitive)
        with QSignalBlocker(self.regex_checkbox):
            self.regex_checkbox.setChecked(self.filter_state.use_regex)
        with QSignalBlocker(self.view_selector):
            self.view_selector.setCurrentIndex(max(0, self.view_selector.findData(view_mode)))
        self.stack.setCurrentIndex(0 if view_mode == VIEW_MODE_STRUCTURED else 1)

        widths = self._load_column_widths()
        for column, width in enumerate(widths):
            self.table_view.setColumnWidth(column, width)

    def _load_column_widths(self) -> tuple[int, ...]:
        raw_value = self._settings.value(f"{HEADER_DIALOG_SETTINGS_GROUP}/column_widths", list(DEFAULT_COLUMN_WIDTHS))
        if isinstance(raw_value, str):
            values = [part.strip() for part in raw_value.split(",") if part.strip()]
        elif isinstance(raw_value, (list, tuple)):
            values = list(raw_value)
        else:
            values = [raw_value]

        widths: list[int] = []
        for value in values:
            try:
                width = int(value)
            except (TypeError, ValueError):
                continue
            if width > 0:
                widths.append(width)

        if len(widths) != len(DEFAULT_COLUMN_WIDTHS):
            return DEFAULT_COLUMN_WIDTHS
        return tuple(widths)

    def _store_preferences(self) -> None:
        self._settings.setValue(f"{HEADER_DIALOG_SETTINGS_GROUP}/view_mode", self.view_state.view_mode)
        self._settings.setValue(f"{HEADER_DIALOG_SETTINGS_GROUP}/filter/scope", self.filter_state.scope)
        self._settings.setValue(
            f"{HEADER_DIALOG_SETTINGS_GROUP}/filter/case_sensitive", self.filter_state.case_sensitive
        )
        self._settings.setValue(f"{HEADER_DIALOG_SETTINGS_GROUP}/filter/use_regex", self.filter_state.use_regex)
        self._settings.setValue(
            f"{HEADER_DIALOG_SETTINGS_GROUP}/column_widths",
            [self.table_view.columnWidth(column) for column in range(self.table_model.columnCount())],
        )

    def _normalized_payload(self, payload: HeaderPayload) -> HeaderPayload:
        raw_text = _normalized_header_text(payload.raw_text)
        cards = payload.cards if payload.cards else parse_header_text(raw_text)
        return HeaderPayload(
            hdu_index=payload.hdu_index,
            name=payload.name,
            kind=payload.kind,
            shape=payload.shape,
            cards=cards,
            raw_text=raw_text,
        )

    def _resolve_hdu_index(self, requested_hdu_index: int | None) -> int:
        available_indices = {payload.hdu_index for payload in self._payloads}
        if requested_hdu_index in available_indices:
            return int(requested_hdu_index)
        if self.view_state.hdu_index in available_indices:
            return self.view_state.hdu_index
        return self._payloads[0].hdu_index

    def _current_payload(self) -> HeaderPayload | None:
        current_hdu_index = self.view_state.hdu_index
        for payload in self._payloads:
            if payload.hdu_index == current_hdu_index:
                return payload
        return None

    def _show_payload(self, hdu_index: int, *, reset_current_match: bool) -> None:
        payload = next((item for item in self._payloads if item.hdu_index == hdu_index), None)
        if payload is None:
            return

        self.header_text = payload.raw_text
        self.view_state.hdu_index = payload.hdu_index
        self.view_state.available_hdus = [
            (item.hdu_index, self._format_hdu_label(item)) for item in self._payloads
        ]
        self.view_state.has_header = bool(payload.cards or payload.raw_text)
        self.view_state.line_count = _line_count(payload.raw_text)

        with QSignalBlocker(self.hdu_combo):
            combo_index = self.hdu_combo.findData(payload.hdu_index)
            self.hdu_combo.setCurrentIndex(max(0, combo_index))

        self.table_model.set_payload(payload)
        self.raw_view.setPlainText(payload.raw_text)
        self._apply_filter(reset_current_match=reset_current_match)
        self._apply_view_state()

    def _apply_filter(self, *, reset_current_match: bool) -> None:
        payload = self._current_payload()
        self.proxy_model.set_filter_state(self.filter_state)

        if payload is None or not self.filter_state.query:
            self._match_cards = []
            self.filter_state.match_count = 0
            self.filter_state.current_match = 0
        else:
            self._match_cards = [card for card in payload.cards if _card_matches(card, self.filter_state)]
            self.filter_state.match_count = len(self._match_cards)
            if not self._match_cards:
                self.filter_state.current_match = 0
            elif reset_current_match or not (1 <= self.filter_state.current_match <= len(self._match_cards)):
                self.filter_state.current_match = 1

        self._store_preferences()
        self._sync_match_selection()

    def _sync_match_selection(self) -> None:
        self._update_match_label()
        self._update_navigation_buttons()

        if self.filter_state.match_count > 0:
            proxy_index = self.proxy_model.index(self.filter_state.current_match - 1, 0)
            if proxy_index.isValid():
                self.table_view.setCurrentIndex(proxy_index)
                self.table_view.selectRow(proxy_index.row())
                self.table_view.scrollTo(proxy_index, QTableView.ScrollHint.PositionAtCenter)
        else:
            self.table_view.clearSelection()

        self._update_raw_highlights()

    def _update_match_label(self) -> None:
        self.result_label.setText(
            self.tr("Match {current}/{total}").format(
                current=self.filter_state.current_match,
                total=self.filter_state.match_count,
            )
        )
        self.line_count_label.setText(self.tr("Lines: {count}").format(count=self.view_state.line_count))

    def _update_navigation_buttons(self) -> None:
        enabled = self.view_state.has_header and self.filter_state.match_count > 0
        self.prev_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)

    def _update_raw_highlights(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        palette = self.raw_view.palette()
        match_color = QColor(palette.color(QPalette.ColorRole.Highlight))
        match_color.setAlpha(64)
        current_color = QColor(palette.color(QPalette.ColorRole.Highlight))
        current_color.setAlpha(128)

        current_card = None
        if 1 <= self.filter_state.current_match <= len(self._match_cards):
            current_card = self._match_cards[self.filter_state.current_match - 1]

        for card in self._match_cards:
            color = current_color if card is current_card else match_color
            for line_number in card.raw_lines or (card.index,):
                selection = self._selection_for_line(line_number, color)
                if selection is not None:
                    selections.append(selection)

        self.raw_view.setExtraSelections(selections)

        if current_card is not None:
            self._move_raw_cursor_to_line((current_card.raw_lines or (current_card.index,))[0])

    def _selection_for_line(self, line_number: int, color: QColor) -> QTextEdit.ExtraSelection | None:
        document = self.raw_view.document()
        block = document.findBlockByLineNumber(line_number - 1)
        if not block.isValid():
            return None
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(color)
        return selection

    def _move_raw_cursor_to_line(self, line_number: int) -> None:
        document = self.raw_view.document()
        block = document.findBlockByLineNumber(line_number - 1)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.raw_view.setTextCursor(cursor)
        self.raw_view.centerCursor()

    def _selected_card(self) -> HeaderCard | None:
        if self._context_card is not None:
            return self._context_card
        current_index = self.table_view.currentIndex()
        if current_index.isValid():
            return self._card_for_proxy_index(current_index)
        if 1 <= self.filter_state.current_match <= len(self._match_cards):
            return self._match_cards[self.filter_state.current_match - 1]
        payload = self._current_payload()
        if payload and payload.cards:
            return payload.cards[0]
        return None

    def _card_for_proxy_index(self, proxy_index: QModelIndex) -> HeaderCard | None:
        if not proxy_index.isValid():
            return None
        source_index = self.proxy_model.mapToSource(proxy_index)
        return self.table_model.card_at(source_index.row())

    def _show_table_context_menu(self, position: QPoint) -> None:
        self._context_card = self._card_for_proxy_index(self.table_view.indexAt(position))
        if self._context_card is None:
            self._context_card = self._selected_card()

        menu = QMenu(self)
        action_copy_key = QAction(self.tr("Copy Key"), self)
        action_copy_value = QAction(self.tr("Copy Value"), self)
        action_copy_card = QAction(self.tr("Copy Card"), self)
        action_copy_matches = QAction(self.tr("Copy All Matching"), self)

        has_card = self._context_card is not None
        action_copy_key.setEnabled(has_card and bool(self._context_card.key if self._context_card else ""))
        action_copy_value.setEnabled(has_card)
        action_copy_card.setEnabled(has_card)
        action_copy_matches.setEnabled(bool(self._current_payload() and (self._match_cards or self.table_model.rowCount() > 0)))

        action_copy_key.triggered.connect(self.copy_selected_key)
        action_copy_value.triggered.connect(self.copy_selected_value)
        action_copy_card.triggered.connect(self.copy_selected_card)
        action_copy_matches.triggered.connect(self.copy_all_matching)

        menu.addAction(action_copy_key)
        menu.addAction(action_copy_value)
        menu.addAction(action_copy_card)
        menu.addSeparator()
        menu.addAction(action_copy_matches)
        menu.exec(self.table_view.viewport().mapToGlobal(position))
        self._context_card = None

    def _handle_filter_text_changed(self, text: str) -> None:
        self.filter_state.query = text
        self.filter_state.current_match = 0
        self._apply_filter(reset_current_match=True)

    def _handle_scope_changed(self, _index: int) -> None:
        self.filter_state.scope = str(self.scope_combo.currentData())
        self.filter_state.current_match = 0
        self._apply_filter(reset_current_match=True)

    def _handle_case_sensitive_changed(self, checked: bool) -> None:
        self.filter_state.case_sensitive = bool(checked)
        self.filter_state.current_match = 0
        self._apply_filter(reset_current_match=True)

    def _handle_regex_changed(self, checked: bool) -> None:
        self.filter_state.use_regex = bool(checked)
        self.filter_state.current_match = 0
        self._apply_filter(reset_current_match=True)

    def _handle_hdu_changed(self, index: int) -> None:
        if index < 0:
            return
        hdu_index = self.hdu_combo.itemData(index)
        if hdu_index is None:
            return
        self._show_payload(int(hdu_index), reset_current_match=True)

    def _handle_view_mode_changed(self, index: int) -> None:
        if index < 0:
            return
        mode = str(self.view_selector.itemData(index))
        if mode not in {VIEW_MODE_STRUCTURED, VIEW_MODE_RAW}:
            mode = VIEW_MODE_STRUCTURED
        self.view_state.view_mode = mode
        self.stack.setCurrentIndex(0 if mode == VIEW_MODE_STRUCTURED else 1)
        self._store_preferences()
        self._sync_match_selection()
        self._apply_view_state()

    def _handle_table_double_clicked(self, index: QModelIndex) -> None:
        if index.column() != 1:
            return
        card = self._card_for_proxy_index(index)
        if card is None:
            return
        self.view_state.view_mode = VIEW_MODE_RAW
        with QSignalBlocker(self.view_selector):
            self.view_selector.setCurrentIndex(max(0, self.view_selector.findData(VIEW_MODE_RAW)))
        self.stack.setCurrentIndex(1)
        self._move_raw_cursor_to_line((card.raw_lines or (card.index,))[0])
        self._store_preferences()
        self._apply_view_state()

    def _handle_section_resized(self, _logical_index: int, _old_size: int, _new_size: int) -> None:
        self._store_preferences()

    def _apply_view_state(self) -> None:
        feedback = self.view_state.feedback
        message = feedback.title or feedback.detail or self.tr("No Header")
        has_header = self.view_state.has_header

        self.feedback_label.setText(message if not has_header else "")
        self.feedback_label.setVisible(bool(feedback.visible) and not has_header)

        for widget in (
            self.hdu_label,
            self.hdu_combo,
            self.view_label,
            self.view_selector,
            self.filter_input,
            self.scope_label,
            self.scope_combo,
            self.case_sensitive_checkbox,
            self.regex_checkbox,
            self.prev_button,
            self.next_button,
            self.result_label,
            self.line_count_label,
            self.stack,
        ):
            widget.setVisible(has_header)

        self.hdu_combo.setEnabled(has_header and self.hdu_combo.count() > 1)
        self.view_selector.setEnabled(has_header)

    def _format_hdu_label(self, payload: HeaderPayload) -> str:
        parts = [self.tr("HDU {index}: {name}").format(index=payload.hdu_index, name=payload.name or f"HDU {payload.hdu_index}")]
        if payload.kind:
            parts.append(payload.kind)
        if payload.shape:
            parts.append("x".join(str(value) for value in payload.shape))
        return " | ".join(parts)

    def _format_card_text(self, card: HeaderCard) -> str:
        if card.kind in {"comment", "history"}:
            return f"{card.key} {card.value}".rstrip()
        if card.kind == "blank":
            return ""
        if card.comment:
            return f"{card.key} = {card.value} / {card.comment}".rstrip()
        if card.value:
            return f"{card.key} = {card.value}".rstrip()
        return card.key


__all__ = ["HeaderDialog", "HeaderFilterProxyModel", "HeaderTableModel"]
