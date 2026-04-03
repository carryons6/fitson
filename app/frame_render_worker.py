from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.fits_data import FITSData
from ..core.fits_service import render_image_u8, render_preview_u8


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
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.generation = generation
        self.frame_index = frame_index
        self.data = data
        self.stretch_name = stretch_name
        self.interval_name = interval_name
        self.preview_dimensions = tuple(sorted(set(preview_dimensions)))

    @Slot()
    def run(self) -> None:
        thread = QThread.currentThread()

        try:
            for max_dimension in self.preview_dimensions:
                preview = render_preview_u8(
                    self.data,
                    self.stretch_name,
                    self.interval_name,
                    max_dimension=max_dimension,
                )
                if preview is not None:
                    self.preview_ready.emit(self.request_id, self.generation, self.frame_index, preview)
                if thread.isInterruptionRequested():
                    return

            image_u8 = render_image_u8(self.data, self.stretch_name, self.interval_name)
            if thread.isInterruptionRequested():
                return
            self.render_ready.emit(self.request_id, self.generation, self.frame_index, image_u8)
        except Exception as exc:
            self.render_error.emit(self.request_id, self.generation, self.frame_index, str(exc))
        finally:
            self.finished.emit(self.request_id)
