from __future__ import annotations

import dataclasses
import multiprocessing
import queue as queue_mod
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ..core.contracts import ROISelection
from ..core.sep_service import SEPParameters
from ..core.source_catalog import SourceCatalog


def _subprocess_entry(
    data: Any,
    params_dict: dict[str, Any],
    out_queue: Any,
    estimate_only: bool = False,
    estimate_threshold: float | None = None,
) -> None:
    """Entry point for the SEP extraction subprocess.

    Runs `sep.extract` in this fresh interpreter (out of the parent's GIL)
    and posts the raw result dict onto `out_queue` for the parent to read.
    """

    try:
        from ..core.sep_subprocess import run_extraction

        result = run_extraction(
            data,
            params_dict,
            estimate_only=estimate_only,
            estimate_threshold=estimate_threshold,
        )
        out_queue.put(("ok", result))
    except BaseException as exc:  # noqa: BLE001 — bubble any failure to parent
        out_queue.put(("error", f"{type(exc).__name__}: {exc}"))


class SEPExtractWorker(QObject):
    """Background worker that runs SEP extraction in a child process.

    `sep.extract` does not release the GIL, so running it in a QThread would
    still block the main event loop. The worker spawns a `multiprocessing`
    child process so the extraction runs in a separate interpreter.

    The worker polls the result queue with a short timeout so `cancel()` can
    promptly terminate the subprocess and let the QThread exit.
    """

    extraction_ready = Signal(int, object, object)
    estimation_ready = Signal(int, object, int)
    extraction_error = Signal(int, str)
    finished = Signal(int)

    _POLL_TIMEOUT_SECONDS = 0.1

    def __init__(
        self,
        *,
        request_id: int,
        data_subarray: Any,
        roi: ROISelection,
        params: SEPParameters,
        wcs: Any = None,
        estimate_only: bool = False,
        estimate_threshold: float | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.data_subarray = data_subarray
        self.roi = roi
        self.params = params
        self.wcs = wcs
        self.estimate_only = estimate_only
        self.estimate_threshold = estimate_threshold
        self._process: Any = None
        self._cancelled = False

    def cancel(self) -> None:
        """Terminate the extraction subprocess if it is still running."""

        self._cancelled = True
        process = self._process
        if process is not None:
            try:
                if process.is_alive():
                    process.terminate()
            except Exception:
                pass

    @Slot()
    def run(self) -> None:
        process: Any = None
        try:
            params_dict = dataclasses.asdict(self.params)
            ctx = multiprocessing.get_context("spawn")
            out_queue = ctx.Queue()
            process = ctx.Process(
                target=_subprocess_entry,
                args=(
                    self.data_subarray,
                    params_dict,
                    out_queue,
                    self.estimate_only,
                    self.estimate_threshold,
                ),
                daemon=True,
            )
            self._process = process
            process.start()

            outcome: tuple[str, Any] | None = None
            while True:
                if self._cancelled:
                    return
                try:
                    outcome = out_queue.get(timeout=self._POLL_TIMEOUT_SECONDS)
                    break
                except queue_mod.Empty:
                    if not process.is_alive():
                        break

            if self._cancelled:
                return
            if outcome is None:
                raise RuntimeError("SEP subprocess exited without posting a result")

            kind, payload = outcome
            if kind != "ok":
                raise RuntimeError(str(payload))

            if self.estimate_only:
                count = int(payload.get("count", 0))
                self.estimation_ready.emit(self.request_id, self.roi, count)
                return

            catalog = SourceCatalog.from_sep_objects(
                payload["objects"],
                x_offset=self.roi.x0,
                y_offset=self.roi.y0,
                wcs=self.wcs,
                background_rms=payload["background_rms"],
                segmentation_map=payload["segmentation_map"],
            )
            self.extraction_ready.emit(self.request_id, self.roi, catalog)
        except Exception as exc:
            if not self._cancelled:
                self.extraction_error.emit(self.request_id, str(exc))
        finally:
            self._process = None
            self._cleanup_process(process)
            self.finished.emit(self.request_id)

    def _cleanup_process(self, process: Any) -> None:
        """Force the subprocess to exit quickly so the QThread can rejoin."""

        if process is None:
            return
        try:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        except Exception:
            pass
        try:
            process.close()
        except Exception:
            pass
