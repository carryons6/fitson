from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QTextEdit, QVBoxLayout

from .contracts import HeaderFilterState, HeaderViewState, ViewFeedbackState


class HeaderDialog(QDialog):
    """FITS header viewer skeleton.

    View contract:
    - Input from `MainWindow`: raw header text.
    - Internal responsibility: search/filter presentation only.
    """

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.header_text = ""
        self.filter_state = HeaderFilterState()
        self.view_state = HeaderViewState()
        self.layout = QVBoxLayout(self)
        self.feedback_label = QLabel("No Header", self)
        self.filter_input = QLineEdit(self)
        self.result_label = QLabel(self)
        self.text_view = QTextEdit(self)

        self.setObjectName("header_dialog")
        self.setWindowTitle("FITS Header")
        self.resize(800, 600)
        self.filter_input.setPlaceholderText("Search header cards")
        self.text_view.setReadOnly(True)
        self.layout.addWidget(self.feedback_label)
        self.layout.addWidget(self.filter_input)
        self.layout.addWidget(self.result_label)
        self.layout.addWidget(self.text_view)
        self.filter_input.textChanged.connect(self.set_filter_text)
        self.filter_input.textChanged.connect(lambda _text: self.apply_filter())
        self._apply_view_state()

    def set_header_text(self, text: str) -> None:
        """Load the raw header text into the dialog.

        Expected caller: `MainWindow.show_header_dialog()`.
        """

        self.header_text = text
        self.view_state.has_header = bool(text.strip())
        self.view_state.line_count = len(text.splitlines()) if text else 0
        self.apply_filter()

    def set_filter_text(self, text: str) -> None:
        """Update the current filter string."""

        self.filter_state.query = text
        if self.filter_input.text() != text:
            self.filter_input.setText(text)

    def set_filter_state(self, state: HeaderFilterState) -> None:
        """Apply structured filter state to the header view."""

        self.filter_state = state

    def current_filter_state(self) -> HeaderFilterState:
        """Return the current structured filter state."""

        return self.filter_state

    def set_view_state(self, state: HeaderViewState) -> None:
        """Apply structured view state to the header dialog."""

        self.view_state = state
        self._apply_view_state()

    def current_view_state(self) -> HeaderViewState:
        """Return the current composite header view state."""

        return self.view_state

    def apply_filter(self) -> None:
        """Apply the current search filter to the header view."""

        lines = self.header_text.splitlines()
        query = self.filter_state.query
        if not query:
            filtered_lines = lines
        else:
            if self.filter_state.case_sensitive:
                filtered_lines = [line for line in lines if query in line]
            else:
                lowered_query = query.lower()
                filtered_lines = [line for line in lines if lowered_query in line.lower()]
        self.filter_state.match_count = len(filtered_lines)
        self.text_view.setPlainText("\n".join(filtered_lines))
        self.result_label.setText(f"Matches: {self.filter_state.match_count}")
        self._apply_view_state()

    def clear(self) -> None:
        """Clear dialog state."""

        self.header_text = ""
        self.filter_state = HeaderFilterState()
        self.view_state = HeaderViewState()
        self.filter_input.clear()
        self.text_view.clear()
        self.result_label.clear()
        self._apply_view_state()

    def set_feedback_state(self, state: ViewFeedbackState) -> None:
        """Apply a feedback state to the header dialog."""

        self.view_state.feedback = state
        self._apply_view_state()

    def _apply_view_state(self) -> None:
        """Refresh feedback and editor visibility from the composite state."""

        feedback = self.view_state.feedback
        message = feedback.title or feedback.detail or "No Header"
        self.feedback_label.setText(message)
        self.feedback_label.setVisible(feedback.visible and not self.view_state.has_header)
