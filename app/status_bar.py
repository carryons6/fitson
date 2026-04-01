from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QStatusBar

from ..core.contracts import PixelSample, ZoomState


class AppStatusBar(QStatusBar):
    """Status-bar skeleton for cursor, WCS, and zoom information.

    View contract:
    - Receives passive display state from `MainWindow`.
    - Does not read canvas or FITS data directly.
    """

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.last_sample = PixelSample()
        self.last_zoom_state = ZoomState()
        self.pixel_label = QLabel("Pixel: (-, -)", self)
        self.value_label = QLabel("Value: -", self)
        self.world_label = QLabel("RA/Dec: - / -", self)
        self.zoom_label = QLabel("Zoom: 100%", self)

        self.addPermanentWidget(self.pixel_label)
        self.addPermanentWidget(self.value_label)
        self.addPermanentWidget(self.world_label, 1)
        self.addPermanentWidget(self.zoom_label)

    def set_pixel_info(self, x: int | None, y: int | None, value: float | None) -> None:
        """Update pixel coordinate and value text."""

        x_text = "-" if x is None else str(x)
        y_text = "-" if y is None else str(y)
        value_text = "-" if value is None else f"{value:.3f}"
        self.pixel_label.setText(f"Pixel: ({x_text}, {y_text})")
        self.value_label.setText(f"Value: {value_text}")

    def set_world_info(self, ra: str | None, dec: str | None) -> None:
        """Update RA/Dec display text."""

        ra_text = ra or "-"
        dec_text = dec or "-"
        self.world_label.setText(f"RA/Dec: {ra_text} / {dec_text}")

    def set_zoom_info(self, zoom_factor: float | None) -> None:
        """Update the zoom display text."""

        percent = 100.0 if zoom_factor is None else zoom_factor * 100.0
        self.zoom_label.setText(f"Zoom: {percent:.0f}%")

    def set_sample(self, sample: PixelSample) -> None:
        """Apply a full cursor sample payload to the status bar."""

        self.last_sample = sample
        self.set_pixel_info(sample.x, sample.y, sample.value)
        self.set_world_info(sample.ra, sample.dec)

    def set_zoom_state(self, zoom_state: ZoomState) -> None:
        """Apply a structured zoom state payload to the status bar."""

        self.last_zoom_state = zoom_state
        self.set_zoom_info(zoom_state.scale_factor)

    def snapshot(self) -> dict[str, Any]:
        """Return a coarse snapshot of status-bar state for tests/debugging."""

        return {
            "sample": self.last_sample,
            "zoom_state": self.last_zoom_state,
        }

    def clear_data(self) -> None:
        """Reset all displayed status values."""

        self.last_sample = PixelSample()
        self.last_zoom_state = ZoomState()
        self.set_pixel_info(None, None, None)
        self.set_world_info(None, None)
        self.set_zoom_info(1.0)
