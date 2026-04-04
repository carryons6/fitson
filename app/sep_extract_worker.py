from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ..core.contracts import ROISelection
from ..core.sep_service import SEPParameters, SEPService


class SEPExtractWorker(QObject):
    """Background worker that runs SEP extraction outside the UI thread."""

    extraction_ready = Signal(int, object, object)
    extraction_error = Signal(int, str)
    finished = Signal(int)

    def __init__(
        self,
        *,
        request_id: int,
        data_subarray: Any,
        roi: ROISelection,
        params: SEPParameters,
        wcs: Any = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.data_subarray = data_subarray
        self.roi = roi
        self.params = params
        self.wcs = wcs

    @Slot()
    def run(self) -> None:
        service = SEPService()

        try:
            catalog = service.extract_from_roi(
                self.data_subarray,
                self.roi,
                params=self.params,
                wcs=self.wcs,
            )
            self.extraction_ready.emit(self.request_id, self.roi, catalog)
        except Exception as exc:
            self.extraction_error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit(self.request_id)
