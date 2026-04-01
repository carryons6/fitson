from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .contracts import ControlEnablementState, SEPFieldSpec, SEPPanelState, ViewFeedbackState
from ..core.sep_service import SEPParameters


class SEPParamsPanel(QWidget):
    """SEP parameter configuration panel skeleton.

    View contract:
    - Owns user-editable SEP controls.
    - Emits typed parameter objects back to `MainWindow`.
    - Does not call `SEPService` directly.
    """

    params_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._params = SEPParameters()
        self._field_specs = self.default_field_specs()
        self._panel_state = SEPPanelState()
        self._field_widgets: dict[str, QWidget] = {}
        self.layout = QVBoxLayout(self)
        self.feedback_label = QLabel(self)
        self.form_group = QGroupBox("SEP Parameters", self)
        self.form_layout = QFormLayout(self.form_group)
        self.reset_button = QPushButton("Reset Defaults", self)

        self.setObjectName("sep_params_panel")
        self.layout.addWidget(self.feedback_label)
        self.layout.addWidget(self.form_group)
        self.layout.addWidget(self.reset_button)
        self._build_form_widgets()
        self.reset_button.clicked.connect(self.reset_defaults)
        self._apply_panel_state()

    def current_params(self) -> SEPParameters:
        """Return the current SEP parameter object."""

        return self._params

    def default_field_specs(self) -> list[SEPFieldSpec]:
        """Return the Phase 1 SEP parameter field specification."""

        return [
            SEPFieldSpec(
                key="thresh",
                label="Detection threshold",
                widget_kind="double_spinbox",
                default_value=3.0,
                minimum=0.5,
                maximum=100.0,
                step=0.5,
                tooltip="Detection threshold in background RMS units.",
            ),
            SEPFieldSpec(
                key="minarea",
                label="Min area",
                widget_kind="spinbox",
                default_value=5,
                minimum=1,
                maximum=1000,
                step=1,
                tooltip="Minimum number of pixels required for detection.",
            ),
            SEPFieldSpec(
                key="deblend_nthresh",
                label="Deblend thresholds",
                widget_kind="spinbox",
                default_value=32,
                minimum=1,
                maximum=128,
                step=1,
                tooltip="Number of thresholds used during deblending.",
            ),
            SEPFieldSpec(
                key="deblend_cont",
                label="Deblend contrast",
                widget_kind="double_spinbox",
                default_value=0.005,
                minimum=0.0001,
                maximum=1.0,
                step=0.0001,
                tooltip="Minimum contrast ratio for deblending.",
            ),
            SEPFieldSpec(
                key="clean",
                label="Clean",
                widget_kind="checkbox",
                default_value=True,
                tooltip="Enable SEP cleaning pass.",
            ),
            SEPFieldSpec(
                key="clean_param",
                label="Clean param",
                widget_kind="double_spinbox",
                default_value=1.0,
                minimum=0.1,
                maximum=10.0,
                step=0.1,
                tooltip="Cleaning aggressiveness parameter.",
            ),
        ]

    def field_specs(self) -> list[SEPFieldSpec]:
        """Return the currently active SEP field specification list."""

        return list(self._field_specs)

    def configure_fields(self, field_specs: list[SEPFieldSpec]) -> None:
        """Install a field specification list for the panel."""

        self._field_specs = list(field_specs)
        self._build_form_widgets()

    def set_panel_state(self, state: SEPPanelState) -> None:
        """Apply structured enablement and feedback state to the panel."""

        self._panel_state = state
        self._apply_panel_state()

    def panel_state(self) -> SEPPanelState:
        """Return the current composite panel state."""

        return self._panel_state

    def load_params(self, params: SEPParameters) -> None:
        """Load a parameter object into the panel.

        Expected caller: `MainWindow.build_ui()` or reset flow.
        """

        self._params = params
        self.apply_params_to_form_state(params)

    def reset_defaults(self) -> None:
        """Reset all controls to the default SEP parameters.

        Expected caller: `MainWindow` reset action.
        """

        default_params = SEPParameters()
        self.apply_params_to_form_state(default_params)
        self.emit_params_changed()

    def params_from_form_state(self) -> SEPParameters:
        """Build a typed parameter object from the current form state."""

        params = SEPParameters()
        for spec in self._field_specs:
            widget = self._field_widgets.get(spec.key)
            if widget is None:
                continue
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                value = widget.value()
            else:
                continue
            setattr(params, spec.key, value)
        self._params = params
        return params

    def apply_params_to_form_state(self, params: SEPParameters) -> None:
        """Push a typed parameter object into the internal form state."""

        self._params = params
        for spec in self._field_specs:
            widget = self._field_widgets.get(spec.key)
            if widget is None:
                continue
            value = getattr(params, spec.key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(value)

    def set_enablement_state(self, state: ControlEnablementState) -> None:
        """Apply enablement state to the panel."""

        self._panel_state.enablement = state
        self._apply_panel_state()

    def set_feedback_state(self, state: ViewFeedbackState) -> None:
        """Apply feedback state to the panel."""

        self._panel_state.feedback = state
        self._apply_panel_state()

    def emit_params_changed(self) -> None:
        """Emit the current parameter object through the public signal."""

        self.params_changed.emit(self.params_from_form_state())

    def _build_form_widgets(self) -> None:
        """Create form widgets from the current field specification list."""

        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
        self._field_widgets.clear()
        for spec in self._field_specs:
            widget = self._make_widget_for_spec(spec)
            self._field_widgets[spec.key] = widget
            self.form_layout.addRow(spec.label, widget)
        self.apply_params_to_form_state(self._params)

    def _make_widget_for_spec(self, spec: SEPFieldSpec) -> QWidget:
        """Create one form widget for a field specification."""

        if spec.widget_kind == "checkbox":
            widget = QCheckBox(self.form_group)
            widget.setChecked(bool(spec.default_value))
            widget.stateChanged.connect(lambda _value, self=self: self.emit_params_changed())
        elif spec.widget_kind == "spinbox":
            widget = QSpinBox(self.form_group)
            if spec.minimum is not None:
                widget.setMinimum(int(spec.minimum))
            if spec.maximum is not None:
                widget.setMaximum(int(spec.maximum))
            if spec.step is not None:
                widget.setSingleStep(int(spec.step))
            widget.setValue(int(spec.default_value))
            widget.valueChanged.connect(lambda _value, self=self: self.emit_params_changed())
        else:
            widget = QDoubleSpinBox(self.form_group)
            if spec.minimum is not None:
                widget.setMinimum(float(spec.minimum))
            if spec.maximum is not None:
                widget.setMaximum(float(spec.maximum))
            if spec.step is not None:
                widget.setSingleStep(float(spec.step))
            widget.setValue(float(spec.default_value))
            widget.valueChanged.connect(lambda _value, self=self: self.emit_params_changed())
        widget.setToolTip(spec.tooltip)
        return widget

    def _apply_panel_state(self) -> None:
        """Refresh enablement and feedback visibility from the composite state."""

        enablement = self._panel_state.enablement
        feedback = self._panel_state.feedback
        self.form_group.setEnabled(enablement.enabled)
        self.reset_button.setEnabled(enablement.enabled)
        message = feedback.title or feedback.detail or enablement.reason
        self.feedback_label.setText(message)
        self.feedback_label.setVisible(bool(message) and feedback.visible)
