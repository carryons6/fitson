from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt


class FramePlayerDock(QDockWidget):
    """Dock panel for multi-frame FITS playback control."""

    frame_changed = Signal(int)  # emits current frame index

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__("Frame Player", parent)
        self.setObjectName("frame_player_dock")

        self._frame_count = 0
        self._playing = False
        self._rendering_current_frame = False
        self._awaiting_current_frame_preview = False
        self._base_info_text = "No frames loaded."
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_frame)

        content = QWidget(self)
        layout = QVBoxLayout(content)

        # --- Frame slider ---
        slider_row = QWidget(content)
        slider_layout = QHBoxLayout(slider_row)
        slider_layout.setContentsMargins(0, 0, 0, 0)

        self.frame_label = QLabel("Frame:", slider_row)
        self.frame_slider = QSlider(Qt.Orientation.Horizontal, slider_row)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_spin = QSpinBox(slider_row)
        self.frame_spin.setMinimum(0)
        self.frame_spin.setMaximum(0)
        self.total_label = QLabel("/ 0", slider_row)

        slider_layout.addWidget(self.frame_label)
        slider_layout.addWidget(self.frame_slider, 1)
        slider_layout.addWidget(self.frame_spin)
        slider_layout.addWidget(self.total_label)
        layout.addWidget(slider_row)

        # --- Playback controls ---
        ctrl_row = QWidget(content)
        ctrl_layout = QHBoxLayout(ctrl_row)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)

        self.first_btn = QPushButton("|<", ctrl_row)
        self.prev_btn = QPushButton("<", ctrl_row)
        self.play_btn = QPushButton("Play", ctrl_row)
        self.next_btn = QPushButton(">", ctrl_row)
        self.last_btn = QPushButton(">|", ctrl_row)

        self.first_btn.setFixedWidth(36)
        self.prev_btn.setFixedWidth(36)
        self.next_btn.setFixedWidth(36)
        self.last_btn.setFixedWidth(36)

        ctrl_layout.addWidget(self.first_btn)
        ctrl_layout.addWidget(self.prev_btn)
        ctrl_layout.addWidget(self.play_btn)
        ctrl_layout.addWidget(self.next_btn)
        ctrl_layout.addWidget(self.last_btn)
        layout.addWidget(ctrl_row)

        # --- Playback parameters ---
        param_row = QWidget(content)
        param_layout = QHBoxLayout(param_row)
        param_layout.setContentsMargins(0, 0, 0, 0)

        param_layout.addWidget(QLabel("FPS:", param_row))
        self.fps_spin = QDoubleSpinBox(param_row)
        self.fps_spin.setRange(0.1, 60.0)
        self.fps_spin.setValue(5.0)
        self.fps_spin.setSingleStep(0.5)
        param_layout.addWidget(self.fps_spin)

        self.loop_btn = QPushButton("Loop", param_row)
        self.loop_btn.setCheckable(True)
        self.loop_btn.setChecked(True)
        param_layout.addWidget(self.loop_btn)

        self.bounce_btn = QPushButton("Bounce", param_row)
        self.bounce_btn.setCheckable(True)
        self.bounce_btn.setChecked(False)
        param_layout.addWidget(self.bounce_btn)

        param_layout.addStretch()
        layout.addWidget(param_row)

        # --- Info ---
        self.info_label = QLabel(self._base_info_text, content)
        layout.addWidget(self.info_label)

        layout.addStretch()
        self.setWidget(content)

        # --- Internal state ---
        self._direction = 1  # 1 = forward, -1 = reverse (for bounce)

        # --- Connections ---
        self.frame_slider.valueChanged.connect(self._on_slider_changed)
        self.frame_spin.valueChanged.connect(self._on_spin_changed)
        self.play_btn.clicked.connect(self._toggle_play)
        self.first_btn.clicked.connect(self._go_first)
        self.prev_btn.clicked.connect(self._go_prev)
        self.next_btn.clicked.connect(self._go_next)
        self.last_btn.clicked.connect(self._go_last)
        self.fps_spin.valueChanged.connect(self._update_timer_interval)

    def set_frame_count(self, count: int) -> None:
        """Update the total number of frames."""

        self._frame_count = count
        max_idx = max(0, count - 1)
        if count < 2 and self._playing:
            self._stop_playback()
        self.frame_slider.setMaximum(max_idx)
        self.frame_spin.setMaximum(max_idx)
        self.set_current_frame(min(self.current_frame(), max_idx))
        self.total_label.setText(f"/ {count}")
        if count > 0:
            self._base_info_text = f"{count} frame(s) loaded."
        else:
            self._base_info_text = "No frames loaded."
        self._refresh_info_label()

    def set_render_state(self, is_rendering: bool, *, has_preview: bool) -> None:
        """Annotate playback UI with the active frame's render progress."""

        self._rendering_current_frame = is_rendering
        self._awaiting_current_frame_preview = is_rendering and not has_preview
        self._refresh_info_label()

    def _refresh_info_label(self) -> None:
        """Rebuild the dock's passive status text."""

        if not self._rendering_current_frame:
            self.info_label.setText(self._base_info_text)
            return

        if self._awaiting_current_frame_preview:
            suffix = " Waiting for preview..."
        else:
            suffix = " Rendering full frame..."
        self.info_label.setText(f"{self._base_info_text}{suffix}")

    def current_frame(self) -> int:
        return self.frame_slider.value()

    def set_current_frame(self, index: int) -> None:
        self.frame_slider.blockSignals(True)
        self.frame_spin.blockSignals(True)
        self.frame_slider.setValue(index)
        self.frame_spin.setValue(index)
        self.frame_slider.blockSignals(False)
        self.frame_spin.blockSignals(False)

    def _on_slider_changed(self, value: int) -> None:
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(value)
        self.frame_spin.blockSignals(False)
        self.frame_changed.emit(value)

    def _on_spin_changed(self, value: int) -> None:
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(value)
        self.frame_slider.blockSignals(False)
        self.frame_changed.emit(value)

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        if self._frame_count < 2:
            return
        self._playing = True
        self._direction = 1
        self.play_btn.setText("Pause")
        self._update_timer_interval()
        self._timer.start()

    def _stop_playback(self) -> None:
        self._playing = False
        self._timer.stop()
        self.play_btn.setText("Play")

    def _update_timer_interval(self) -> None:
        fps = self.fps_spin.value()
        self._timer.setInterval(int(1000.0 / fps))

    def _advance_frame(self) -> None:
        if self._awaiting_current_frame_preview:
            return

        current = self.frame_slider.value()
        last = self._frame_count - 1

        if self.bounce_btn.isChecked():
            nxt = current + self._direction
            if nxt > last:
                self._direction = -1
                nxt = current + self._direction
            elif nxt < 0:
                self._direction = 1
                nxt = current + self._direction
            self.frame_slider.setValue(max(0, min(nxt, last)))
        elif self.loop_btn.isChecked():
            self.frame_slider.setValue((current + 1) % self._frame_count)
        else:
            if current < last:
                self.frame_slider.setValue(current + 1)
            else:
                self._stop_playback()

    def _go_first(self) -> None:
        self.frame_slider.setValue(0)

    def _go_prev(self) -> None:
        self.frame_slider.setValue(max(0, self.frame_slider.value() - 1))

    def _go_next(self) -> None:
        self.frame_slider.setValue(min(self._frame_count - 1, self.frame_slider.value() + 1))

    def _go_last(self) -> None:
        self.frame_slider.setValue(max(0, self._frame_count - 1))
