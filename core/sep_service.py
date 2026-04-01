from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import sep

from .contracts import ROISelection
from .source_catalog import SourceCatalog


@dataclass(slots=True)
class SEPParameters:
    """User-facing SEP parameters for Phase 1."""

    thresh: float = 3.0
    minarea: int = 5
    deblend_nthresh: int = 32
    deblend_cont: float = 0.005
    clean: bool = True
    clean_param: float = 1.0


class SEPService:
    """SEP extraction service skeleton.

    Service contract:
    - Input: ROI data slice, parameter set, absolute ROI origin, optional WCS.
    - Output: `SourceCatalog`.
    - Consumer: `MainWindow.handle_roi_selected()`.
    """

    def __init__(self) -> None:
        self.params = SEPParameters()

    def default_params(self) -> SEPParameters:
        """Return the default parameter set.

        Expected caller: `SEPParamsPanel` during initialization and reset.
        """

        return SEPParameters()

    def validate_params(self, params: SEPParameters) -> None:
        """Validate a parameter set before extraction.

        Raises ValueError if any parameter is out of range.
        """

        if params.thresh <= 0:
            raise ValueError(f"thresh must be positive, got {params.thresh}")
        if params.minarea < 1:
            raise ValueError(f"minarea must be >= 1, got {params.minarea}")

    def params_to_payload(self, params: SEPParameters) -> dict[str, Any]:
        """Convert typed parameters into a simple service payload."""

        return {
            "thresh": params.thresh,
            "minarea": params.minarea,
            "deblend_nthresh": params.deblend_nthresh,
            "deblend_cont": params.deblend_cont,
            "clean": params.clean,
            "clean_param": params.clean_param,
        }

    def extract(
        self,
        data_subarray: np.ndarray,
        params: SEPParameters | None = None,
        *,
        x_offset: int = 0,
        y_offset: int = 0,
        wcs: Any = None,
    ) -> SourceCatalog:
        """Run SEP extraction on the given ROI and return a catalog.

        Expected flow:
        `ImageCanvas.roi_selected` -> `MainWindow.handle_roi_selected()`
        -> `SEPService.extract()` -> `SourceTableDock.populate()`
        and `ImageCanvas.draw_sources()`.
        """

        p = params or self.params
        self.validate_params(p)

        data = np.ascontiguousarray(data_subarray, dtype=np.float64)
        bkg = sep.Background(data)
        data_sub = data - bkg

        objects = sep.extract(
            data_sub,
            thresh=p.thresh,
            err=bkg.globalrms,
            minarea=p.minarea,
            deblend_nthresh=p.deblend_nthresh,
            deblend_cont=p.deblend_cont,
            clean=p.clean,
            clean_param=p.clean_param,
        )

        return SourceCatalog.from_sep_objects(
            objects,
            x_offset=x_offset,
            y_offset=y_offset,
            wcs=wcs,
        )

    def extract_from_roi(
        self,
        data_subarray: np.ndarray,
        roi: ROISelection,
        params: SEPParameters | None = None,
        *,
        wcs: Any = None,
    ) -> SourceCatalog:
        """Convenience wrapper using a structured ROI selection object."""

        return self.extract(
            data_subarray,
            params=params,
            x_offset=roi.x0,
            y_offset=roi.y0,
            wcs=wcs,
        )
