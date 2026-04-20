from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .contracts import TableColumnSpec


class CatalogFieldDialog(QDialog):
    """Dialog for choosing which source fields are shown and exported."""

    def __init__(self, columns: Sequence[TableColumnSpec], parent: Any | None = None) -> None:
        super().__init__(parent)
        self._default_columns = [
            TableColumnSpec(
                key=column.key,
                title=column.title,
                width_hint=column.width_hint,
                visible=column.visible,
                alignment=column.alignment,
            )
            for column in columns
        ]
        self._checkboxes: dict[str, QCheckBox] = {}

        self.setObjectName("catalog_field_dialog")
        self.setWindowTitle(self.tr("Target Info Fields"))
        self.resize(420, 320)

        self.layout = QVBoxLayout(self)
        self.description_label = QLabel(
            self.tr("Choose which fields should be shown for right-drag target extraction results."),
            self,
        )
        self.description_label.setWordWrap(True)
        self.validation_label = QLabel("", self)

        self.checkbox_host = QWidget(self)
        self.checkbox_layout = QGridLayout(self.checkbox_host)
        self.checkbox_layout.setContentsMargins(0, 0, 0, 0)

        self.reset_button = QPushButton(self.tr("Reset Defaults"), self)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )

        self.layout.addWidget(self.description_label)
        self.layout.addWidget(self.validation_label)
        self.layout.addWidget(self.checkbox_host)
        self.layout.addWidget(self.reset_button)
        self.layout.addWidget(self.button_box)

        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText(self.tr("OK"))
        cancel_button = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText(self.tr("Cancel"))

        self._build_checkboxes(columns)
        self.reset_button.clicked.connect(self.reset_defaults)
        self.button_box.accepted.connect(self._accept_if_valid)
        self.button_box.rejected.connect(self.reject)

    def selected_columns(self) -> list[TableColumnSpec]:
        """Return a visibility-updated column list preserving column order."""

        columns: list[TableColumnSpec] = []
        for column in self._default_columns:
            visible = self._checkboxes[column.key].isChecked()
            columns.append(
                TableColumnSpec(
                    key=column.key,
                    title=column.title,
                    width_hint=column.width_hint,
                    visible=visible,
                    alignment=column.alignment,
                )
            )
        return columns

    def reset_defaults(self) -> None:
        """Restore all fields to visible by default."""

        for checkbox in self._checkboxes.values():
            checkbox.setChecked(True)
        self.validation_label.clear()

    def _build_checkboxes(self, columns: Sequence[TableColumnSpec]) -> None:
        """Create one checkbox per available catalog column."""

        for index, column in enumerate(columns):
            checkbox = QCheckBox(self.tr(column.title), self.checkbox_host)
            checkbox.setChecked(column.visible)
            row = index // 2
            col = index % 2
            self.checkbox_layout.addWidget(checkbox, row, col)
            self._checkboxes[column.key] = checkbox

    def _accept_if_valid(self) -> None:
        """Accept only when at least one field stays enabled."""

        if not any(checkbox.isChecked() for checkbox in self._checkboxes.values()):
            self.validation_label.setText(self.tr("Select at least one field."))
            return
        self.accept()
