from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.fits_data import FITSData
from ..core.fits_service import compute_interval_limits, render_image_u8, render_preview_u8


class FrameRenderWorker(QObject):
    """Background worker that renders a single frame preview and full image."""

    preview_ready = Signal(int, int, int, object)
    render_ready = Signal(int, int, int, object)
    render_error = Signal(int, int, int, str)
    finished = Signal(int)

    def __init__(
        self,
        *,
        request_id: int,
        generation: int,
        frame_index: int,
        data: FITSData,
        stretch_name: str,
        interval_name: str,
        preview_dimensions: tuple[int, ...] = (1024, 2048),
        manual_limits: tuple[float, float] | None = None,
        preview_only: bool = False,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.generation = generation
        self.frame_index = frame_index
        self.data = data
        self.stretch_name = stretch_name
        self.interval_name = interval_name
        self.preview_dimensions = tuple(sorted(set(preview_dimensions)))
        self.manual_limits = manual_limits
        self.preview_only = preview_only

    @Slot()
    def run(self) -> None:
        thread = QThread.currentThread()

        try:
            effective_interval, effective_manual_limits = self._resolve_shared_limits()

            for max_dimension in self.preview_dimensions:
                preview = render_preview_u8(
                    self.data,
                    self.stretch_name,
                    effective_interval,
                    max_dimension=max_dimension,
                    manual_limits=effective_manual_limits,
                )
                if preview is not None:
                    self.preview_ready.emit(self.request_id, self.generation, self.frame_index, preview)
                if thread.isInterruptionRequested():
                    return

            if self.preview_only:
                return

            image_u8 = render_image_u8(
                self.data,
                self.stretch_name,
                effective_interval,
                manual_limits=effective_manual_limits,
            )
            if thread.isInterruptionRequested():
                return
            self.render_ready.emit(self.request_id, self.generation, self.frame_index, image_u8)
        except Exception as exc:
            self.render_error.emit(self.request_id, self.generation, self.frame_index, str(exc))
        finally:
            self.finished.emit(self.request_id)

    def _resolve_shared_limits(self) -> tuple[str, tuple[float, float] | None]:
        """Compute interval limits once so preview and full render share them.

        For non-Manual intervals (e.g. ZScale) the limits would otherwise be
        recomputed independently per render stage. By precomputing them and
        switching downstream calls to ``"Manual"`` we avoid that redundant
        work and also guarantee the preview and final image align visually.
        """

        if self.interval_name == "Manual":
            return self.interval_name, self.manual_limits

        shared = compute_interval_limits(
            self.data,
            self.interval_name,
            manual_limits=self.manual_limits,
        )
        if shared is None:
            return self.interval_name, self.manual_limits
        return "Manual", shared
