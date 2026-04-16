from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.fits_data import FITSData
from ..core.fits_service import render_preview_u8


class FITSLoadWorker(QObject):
    """Background worker that loads one or more FITS files off the UI thread."""

    file_loaded = Signal(object, object)
    file_error = Signal(str, str)
    progress = Signal(int, int, str)
    finished = Signal()

    def __init__(
        self,
        paths: list[str],
        hdu_index: int | None = None,
        *,
        source_group_start: int = 0,
        preview_first_frame: bool = False,
        preview_each_frame: bool = False,
        stretch_name: str = "Linear",
        interval_name: str = "ZScale",
        preview_max_dimension: int = 2048,
        manual_limits: tuple[float, float] | None = None,
    ) -> None:
        super().__init__()
        self.paths = list(paths)
        self.hdu_index = hdu_index
        self.source_group_start = int(source_group_start)
        self.preview_first_frame = preview_first_frame
        self.preview_each_frame = preview_each_frame
        self.stretch_name = stretch_name
        self.interval_name = interval_name
        self.preview_max_dimension = preview_max_dimension
        self.manual_limits = manual_limits

    @Slot()
    def run(self) -> None:
        total = len(self.paths)
        thread = QThread.currentThread()
        preview_pending = self.preview_first_frame

        for index, path in enumerate(self.paths, start=1):
            if thread.isInterruptionRequested():
                break
            try:
                frames = FITSData.load_frames(
                    path,
                    self.hdu_index,
                    source_group_id=self.source_group_start + index - 1,
                )
            except Exception as exc:
                self.file_error.emit(path, str(exc))
            else:
                for data in frames:
                    preview_image_u8 = None
                    if self.preview_each_frame:
                        preview_image_u8 = self._render_preview(data)
                    elif preview_pending:
                        preview_pending = False
                        preview_image_u8 = self._render_preview(data)
                    self.file_loaded.emit(data, preview_image_u8)
                    if thread.isInterruptionRequested():
                        break
            self.progress.emit(index, total, path)
            if thread.isInterruptionRequested():
                break

        self.finished.emit()

    def _render_preview(self, data: FITSData):
        """Render a fast preview for the first successfully loaded frame."""

        return render_preview_u8(
            data,
            self.stretch_name,
            self.interval_name,
            max_dimension=self.preview_max_dimension,
            manual_limits=self.manual_limits,
        )
