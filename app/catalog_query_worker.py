from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.catalog_service import CatalogQuery, query_gaia


class GaiaQueryWorker(QObject):
    """Background adapter for the bounded Gaia catalog service."""

    finished = Signal()
    result_ready = Signal(object)
    query_error = Signal(str)

    def __init__(self, query: CatalogQuery) -> None:
        super().__init__()
        self.query = query
        self._cancelled = False
        self._active_response = None

    def cancel(self) -> None:
        self._cancelled = True
        response = self._active_response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def _observe_response(self, response) -> None:  # noqa: ANN001
        self._active_response = response

    def _is_cancelled(self) -> bool:
        return self._cancelled or QThread.currentThread().isInterruptionRequested()

    @Slot()
    def run(self) -> None:
        try:
            if self._is_cancelled():
                return
            sources = query_gaia(
                self.query,
                cancel_check=self._is_cancelled,
                response_observer=self._observe_response,
            )
            if not self._is_cancelled():
                self.result_ready.emit(sources)
        except Exception as exc:
            if not self._is_cancelled():
                self.query_error.emit(str(exc))
        finally:
            self.finished.emit()
