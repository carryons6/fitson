from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QStatusBar

from ..core.contracts import PixelSample, ZoomState


class AppStatusBar(QStatusBar):
    """Status-bar skeleton for cursor, WCS, and zoom information.

    View contract:
    - Receives passive display state from `MainWindow`.
    - Does not read canvas or FITS data directly.
    """

    cancel_requested = Signal()
    continue_requested = Signal()
    error_details_requested = Signal()

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.last_sample = PixelSample()
        self.last_zoom_state = ZoomState()
        self._latest_error_title = ""
        self._latest_error_detail = ""

        self.activity_label = QLabel("", self)
        self.activity_label.setMinimumWidth(220)
        self.activity_progress = QProgressBar(self)
        self.activity_progress.setFixedWidth(180)
        self.activity_progress.setTextVisible(False)
        self.activity_cancel_btn = QPushButton(self.tr("Cancel"), self)
        self.activity_cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.activity_continue_btn = QPushButton(self.tr("Continue"), self)
        self.activity_continue_btn.clicked.connect(self.continue_requested.emit)

        self.error_label = QLabel("", self)
        self.error_button = QPushButton(self.tr("Details"), self)
        self.error_button.clicked.connect(self.error_details_requested.emit)

        self.pixel_label = QLabel(self.tr("Pixel: (-, -)"), self)
        self.value_label = QLabel(self.tr("Value: -"), self)
        self.world_label = QLabel(self.tr("RA/Dec: - / -"), self)
        self.frame_label = QLabel("", self)
        self.view_mode_label = QLabel("", self)
        self.zoom_label = QLabel(self.tr("Zoom: 100%"), self)

        for widget in (
            self.activity_label,
            self.activity_progress,
            self.activity_continue_btn,
            self.activity_cancel_btn,
            self.error_label,
            self.error_button,
        ):
            widget.setVisible(False)
            self.addPermanentWidget(widget)

        self.addPermanentWidget(self.pixel_label)
        self.addPermanentWidget(self.value_label)
        self.addPermanentWidget(self.world_label, 1)
        self.addPermanentWidget(self.view_mode_label)
        self.addPermanentWidget(self.frame_label)
        self.addPermanentWidget(self.zoom_label)

    def set_view_mode_label(self, text: str) -> None:
        """Show a persistent indicator of the current view mode (e.g. BKG)."""

        self.view_mode_label.setText(text)

    def set_pixel_info(self, x: int | None, y: int | None, value: float | None) -> None:
        """Update pixel coordinate and value text."""

        x_text = "-" if x is None else str(x)
        y_text = "-" if y is None else str(y)
        value_text = "-" if value is None else f"{value:.3f}"
        self.pixel_label.setText(
            self.tr("Pixel: ({x}, {y})").format(x=x_text, y=y_text)
        )
        self.value_label.setText(self.tr("Value: {value}").format(value=value_text))

    def set_world_info(self, ra: str | None, dec: str | None) -> None:
        """Update RA/Dec display text."""

        ra_text = ra or "-"
        dec_text = dec or "-"
        self.world_label.setText(
            self.tr("RA/Dec: {ra} / {dec}").format(ra=ra_text, dec=dec_text)
        )

    def set_zoom_info(self, zoom_factor: float | None) -> None:
        """Update the zoom display text."""

        percent = 100.0 if zoom_factor is None else zoom_factor * 100.0
        self.zoom_label.setText(self.tr("Zoom: {percent}%").format(percent=f"{percent:.0f}"))

    def set_sample(self, sample: PixelSample) -> None:
        """Apply a full cursor sample payload to the status bar."""

        self.last_sample = sample
        self.set_pixel_info(sample.x, sample.y, sample.value)
        self.set_world_info(sample.ra, sample.dec)

    def set_zoom_state(self, zoom_state: ZoomState) -> None:
        """Apply a structured zoom state payload to the status bar."""

        self.last_zoom_state = zoom_state
        self.set_zoom_info(zoom_state.scale_factor)

    def set_activity(
        self,
        text: str,
        *,
        progress_value: int | None = None,
        progress_max: int | None = None,
        cancellable: bool = False,
    ) -> None:
        """Show a persistent task indicator with optional progress and cancel affordance."""

        self.activity_label.setText(text)
        self.activity_label.setVisible(bool(text))
        if progress_max is None:
            self.activity_progress.setVisible(False)
        else:
            max_value = max(0, int(progress_max))
            current_value = 0 if progress_value is None else max(0, int(progress_value))
            if max_value <= 0:
                self.activity_progress.setRange(0, 0)
                self.activity_progress.setValue(0)
            else:
                self.activity_progress.setRange(0, max_value)
                self.activity_progress.setValue(min(current_value, max_value))
            self.activity_progress.setVisible(True)
        self.activity_cancel_btn.setVisible(cancellable)
        self.activity_continue_btn.setVisible(False)

    def set_prompt(
        self,
        text: str,
        *,
        continue_label: str | None = None,
        cancel_label: str | None = None,
    ) -> None:
        """Show a non-modal Continue/Cancel prompt inline with the activity slot."""

        self.activity_label.setText(text)
        self.activity_label.setVisible(bool(text))
        self.activity_progress.setVisible(False)
        if continue_label is None:
            continue_label = self.tr("Continue")
        if cancel_label is None:
            cancel_label = self.tr("Cancel")
        self.activity_continue_btn.setText(continue_label)
        self.activity_continue_btn.setVisible(True)
        self.activity_continue_btn.setDefault(True)
        self.activity_cancel_btn.setText(cancel_label)
        self.activity_cancel_btn.setVisible(True)

    def clear_activity(self) -> None:
        """Hide the persistent task indicator widgets."""

        self.activity_label.clear()
        self.activity_label.setVisible(False)
        self.activity_progress.reset()
        self.activity_progress.setVisible(False)
        self.activity_cancel_btn.setText(self.tr("Cancel"))
        self.activity_cancel_btn.setVisible(False)
        self.activity_continue_btn.setText(self.tr("Continue"))
        self.activity_continue_btn.setVisible(False)

    def show_error_indicator(self, title: str, detail: str) -> None:
        """Expose the latest error inline with an optional details affordance."""

        self._latest_error_title = title
        self._latest_error_detail = detail
        self.error_label.setText(f"{title}:")
        self.error_label.setVisible(True)
        self.error_button.setToolTip(detail)
        self.error_button.setVisible(True)

    def clear_error_indicator(self) -> None:
        """Hide any previously stored error summary."""

        self._latest_error_title = ""
        self._latest_error_detail = ""
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.error_button.setToolTip("")
        self.error_button.setVisible(False)

    def latest_error(self) -> tuple[str, str]:
        """Return the most recent stored error summary."""

        return self._latest_error_title, self._latest_error_detail

    def snapshot(self) -> dict[str, Any]:
        """Return a coarse snapshot of status-bar state for tests/debugging."""

        return {
            "sample": self.last_sample,
            "zoom_state": self.last_zoom_state,
            "activity_text": self.activity_label.text(),
            "activity_visible": self.activity_label.isVisible(),
            "has_error": self.error_button.isVisible(),
        }

    def set_frame_info(self, current: int, total: int) -> None:
        """Update frame counter display."""

        if total <= 1:
            self.frame_label.setText("")
        else:
            self.frame_label.setText(
                self.tr("Frame: {current}/{total}").format(current=current + 1, total=total)
            )

    def clear_data(self) -> None:
        """Reset all displayed status values."""

        self.last_sample = PixelSample()
        self.last_zoom_state = ZoomState()
        self.clear_activity()
        self.clear_error_indicator()
        self.set_pixel_info(None, None, None)
        self.set_world_info(None, None)
        self.set_zoom_info(1.0)
        self.frame_label.setText("")
