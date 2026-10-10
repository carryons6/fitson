from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.contracts import RenderResult, ResolvedRenderSpec
from ..core.fits_data import FITSData
from ..core.fits_service import (
    compute_interval_limits,
    render_image_u8,
    render_preview_result,
    render_preview_u8,
)


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
        sampled_previews: bool = False,
        resolved_spec: ResolvedRenderSpec | None = None,
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
        self.sampled_previews = sampled_previews
        self.resolved_spec = resolved_spec

    @Slot()
    def run(self) -> None:
        thread = QThread.currentThread()

        try:
            spec = self._resolve_render_spec()
            preview_renderer = render_preview_result if self.sampled_previews else render_preview_u8

            for max_dimension in self.preview_dimensions:
                preview = preview_renderer(
                    self.data,
                    self.stretch_name,
                    self.interval_name,
                    max_dimension=max_dimension,
                    resolved_spec=spec,
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
                self.interval_name,
                resolved_spec=spec,
            )
            if thread.isInterruptionRequested():
                return
            result = image_u8
            if self.sampled_previews:
                height, width = (0, 0) if self.data.data is None else self.data.data.shape[:2]
                result = RenderResult(
                    image_u8=image_u8,
                    width=width,
                    height=height,
                    invalid_pixels=self.data.invalid_pixels,
                    resolved_spec=spec,
                )
            self.render_ready.emit(self.request_id, self.generation, self.frame_index, result)
        except Exception as exc:
            self.render_error.emit(self.request_id, self.generation, self.frame_index, str(exc))
        finally:
            self.finished.emit(self.request_id)

    def _resolve_render_spec(self) -> ResolvedRenderSpec:
        """Keep one immutable mapping, including constant/all-invalid frames."""

        if self.resolved_spec is not None:
            return self.resolved_spec
        return ResolvedRenderSpec(
            stretch_name=self.stretch_name,
            interval_name=self.interval_name,
            limits=compute_interval_limits(
                self.data,
                self.interval_name,
                manual_limits=self.manual_limits,
            ),
        )
