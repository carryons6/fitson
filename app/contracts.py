from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ViewFeedbackState:
    """Generic empty/error/ready feedback state for a view."""

    status: str = "empty"
    title: str = ""
    detail: str = ""
    visible: bool = False


@dataclass(slots=True)
class ControlEnablementState:
    """Enabled/disabled state plus optional reason text."""

    enabled: bool = False
    reason: str = ""


@dataclass(slots=True)
class CanvasImageState:
    """Presentation state for the image currently shown on the canvas."""

    width: int = 0
    height: int = 0
    has_image: bool = False
    image_label: str = ""
    feedback: ViewFeedbackState = field(default_factory=ViewFeedbackState)


@dataclass(slots=True)
class CanvasOverlayState:
    """Presentation state for overlays drawn on top of the image."""

    source_count: int = 0
    highlighted_index: int | None = None
    roi_visible: bool = False
    feedback: ViewFeedbackState = field(default_factory=ViewFeedbackState)


@dataclass(slots=True)
class TableColumnSpec:
    """Column metadata for the source table."""

    key: str
    title: str
    width_hint: int = 100
    visible: bool = True
    alignment: str = "left"


@dataclass(slots=True)
class TableRowViewModel:
    """One rendered row for the source table view."""

    row_index: int
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableSelectionState:
    """Current selection state for the source table."""

    selected_row: int | None = None
    row_count: int = 0


@dataclass(slots=True)
class TableViewState:
    """Composite state for the source-table dock."""

    row_count: int = 0
    has_catalog: bool = False
    selection: TableSelectionState = field(default_factory=TableSelectionState)
    feedback: ViewFeedbackState = field(default_factory=ViewFeedbackState)


@dataclass(slots=True)
class HeaderFilterState:
    """Filter state applied to the header viewer."""

    query: str = ""
    case_sensitive: bool = False
    match_count: int = 0


@dataclass(slots=True)
class HeaderViewState:
    """Composite state for the FITS header dialog."""

    has_header: bool = False
    line_count: int = 0
    feedback: ViewFeedbackState = field(default_factory=ViewFeedbackState)


@dataclass(slots=True)
class SEPFieldSpec:
    """Field metadata for one SEP parameter control."""

    key: str
    label: str
    widget_kind: str
    default_value: Any
    minimum: Any | None = None
    maximum: Any | None = None
    step: Any | None = None
    tooltip: str = ""


@dataclass(slots=True)
class RenderControlState:
    """Toolbar render-control state for stretch and interval selectors."""

    available_stretches: tuple[str, ...] = ()
    available_intervals: tuple[str, ...] = ()
    current_stretch: str = ""
    current_interval: str = ""
    enabled: bool = False
    disabled_reason: str = ""


@dataclass(slots=True)
class SEPPanelState:
    """Composite state for the SEP parameter panel."""

    enablement: ControlEnablementState = field(default_factory=ControlEnablementState)
    feedback: ViewFeedbackState = field(default_factory=ViewFeedbackState)
