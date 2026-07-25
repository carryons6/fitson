from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.fits_data import FITSData
from ..core.fits_service import render_preview_u8


logger = logging.getLogger(__name__)


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
        preview_pending = self.preview_first_frame
        thread = None

        try:
            thread = QThread.currentThread()
            for index, path in enumerate(self.paths, start=1):
                if thread.isInterruptionRequested():
                    break

                error: Exception | None = None
                try:
                    frames = FITSData.load_frames(
                        path,
                        self.hdu_index,
                        source_group_id=self.source_group_start + index - 1,
                    )
                    if thread.isInterruptionRequested():
                        break
                    if not frames:
                        raise ValueError("The selected HDU produced no image frames.")

                    for data in frames:
                        if thread.isInterruptionRequested():
                            break

                        preview_image_u8 = None
                        consumes_first_preview = False
                        if self.preview_each_frame:
                            preview_image_u8, _preview_failed = self._render_preview_result(data, path)
                        elif preview_pending:
                            preview_image_u8, preview_failed = self._render_preview_result(data, path)
                            consumes_first_preview = not preview_failed

                        # Preview rendering can be expensive; do not publish a
                        # stale result when cancellation arrived meanwhile.
                        if thread.isInterruptionRequested():
                            break
                        self.file_loaded.emit(data, preview_image_u8)
                        if consumes_first_preview:
                            preview_pending = False
                except Exception as exc:
                    error = exc

                if error is not None:
                    self._emit_file_error(path, error)
                if thread.isInterruptionRequested():
                    break

                try:
                    self.progress.emit(index, total, path)
                except Exception as exc:
                    self._emit_file_error(path, exc)
                if thread.isInterruptionRequested():
                    break
        finally:
            # MainWindow relies on this signal to tear down its QThread even
            # when loading, preview rendering, or a result signal fails.
            self.finished.emit()

    def _emit_file_error(self, path: str, error: Exception) -> None:
        """Report a per-file failure without jeopardizing ``finished``."""

        try:
            self.file_error.emit(path, str(error) or type(error).__name__)
        except Exception:
            # A failing receiver must not strand the worker thread.
            pass

    def _render_preview(self, data: FITSData):
        """Render a fast preview for the first successfully loaded frame."""

        return render_preview_u8(
            data,
            self.stretch_name,
            self.interval_name,
            max_dimension=self.preview_max_dimension,
            manual_limits=self.manual_limits,
        )

    def _render_preview_result(self, data: FITSData, path: str) -> tuple[object, bool]:
        """Return ``(preview, failed)`` without making preview errors fatal."""

        try:
            return self._render_preview(data), False
        except MemoryError:
            # Continuing after genuine memory exhaustion would make recovery
            # less likely; let the per-file error path stop this file.
            raise
        except Exception as exc:
            logger.warning("Preview unavailable for %s frame %s: %s", path, data.frame_index, exc)
            return None, True
