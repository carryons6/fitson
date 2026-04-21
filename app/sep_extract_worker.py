from __future__ import annotations

import os
import sys


def _register_frozen_dll_directories() -> None:
    # PyInstaller spawn children re-import this module to locate `_subprocess_entry`.
    # On Windows that re-import must succeed before numpy loads, so make the bundled
    # BLAS/MKL DLLs discoverable via `os.add_dll_directory` ahead of `import numpy`.
    if not getattr(sys, "frozen", False):
        return
    if not hasattr(os, "add_dll_directory"):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    candidates = [
        meipass,
        os.path.join(meipass, "Library", "bin"),
        os.path.join(meipass, "numpy.libs"),
        os.path.join(meipass, "numpy", ".libs"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            try:
                os.add_dll_directory(path)
            except OSError:
                pass


_register_frozen_dll_directories()

import dataclasses
import multiprocessing
from multiprocessing import shared_memory
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from ..core.contracts import ROISelection
from ..core.sep_service import SEPParameters
from ..core.source_catalog import SourceCatalog


def _subprocess_entry(
    shared_array: dict[str, Any],
    params_dict: dict[str, Any],
    result_conn: Any,
    estimate_only: bool = False,
    estimate_threshold: float | None = None,
) -> None:
    """Entry point for the SEP extraction subprocess."""

    shm: shared_memory.SharedMemory | None = None
    try:
        from ..core.sep_subprocess import run_extraction

        shm = shared_memory.SharedMemory(name=str(shared_array["name"]))
        data = np.ndarray(
            tuple(shared_array["shape"]),
            dtype=np.dtype(shared_array["dtype"]),
            buffer=shm.buf,
        )
        result = run_extraction(
            data,
            params_dict,
            estimate_only=estimate_only,
            estimate_threshold=estimate_threshold,
        )
        result_conn.send(("ok", result))
    except BaseException as exc:  # noqa: BLE001 - bubble any failure to parent
        try:
            result_conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except Exception:
            pass
    finally:
        try:
            result_conn.close()
        except Exception:
            pass
        if shm is not None:
            try:
                shm.close()
            except Exception:
                pass


class SEPExtractWorker(QObject):
    """Background worker that runs SEP extraction in a child process.

    `sep.extract` does not release the GIL, so running it in a QThread would
    still block the main event loop. The worker spawns a `multiprocessing`
    child process so the extraction runs in a separate interpreter.

    The worker polls the result pipe with a short timeout so `cancel()` can
    promptly terminate the subprocess and let the QThread exit.
    """

    extraction_ready = Signal(int, object, object)
    estimation_ready = Signal(int, object, int)
    extraction_error = Signal(int, str)
    finished = Signal(int)

    _POLL_TIMEOUT_SECONDS = 0.05
    _TERMINATE_JOIN_TIMEOUT_SECONDS = 0.25
    _KILL_JOIN_TIMEOUT_SECONDS = 0.25

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
        self._terminate_process(self._process)

    @Slot()
    def run(self) -> None:
        process: Any = None
        parent_conn: Any = None
        child_conn: Any = None
        shared_block: shared_memory.SharedMemory | None = None
        try:
            if self._cancelled:
                return
            params_dict = dataclasses.asdict(self.params)
            ctx = multiprocessing.get_context("spawn")
            shared_block, shared_spec = self._share_array(self.data_subarray)
            if self._cancelled:
                return
            parent_conn, child_conn = ctx.Pipe(duplex=False)
            process = ctx.Process(
                target=_subprocess_entry,
                args=(
                    shared_spec,
                    params_dict,
                    child_conn,
                    self.estimate_only,
                    self.estimate_threshold,
                ),
                daemon=True,
            )
            self._process = process
            process.start()
            child_conn.close()
            child_conn = None

            outcome: tuple[str, Any] | None = None
            while True:
                if self._cancelled:
                    return
                try:
                    if parent_conn.poll(self._POLL_TIMEOUT_SECONDS):
                        outcome = parent_conn.recv()
                        break
                    if not process.is_alive():
                        if parent_conn.poll():
                            outcome = parent_conn.recv()
                        break
                except (EOFError, OSError):
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
            self._close_conn(parent_conn)
            self._close_conn(child_conn)
            self._process = None
            self._cleanup_process(process)
            self._cleanup_shared_memory(shared_block)
            self.finished.emit(self.request_id)

    def _cleanup_process(self, process: Any) -> None:
        """Force the subprocess to exit quickly so the QThread can rejoin."""

        if process is None:
            return
        try:
            if process.is_alive():
                process.terminate()
                process.join(timeout=self._TERMINATE_JOIN_TIMEOUT_SECONDS)
            if process.is_alive():
                process.kill()
                process.join(timeout=self._KILL_JOIN_TIMEOUT_SECONDS)
        except Exception:
            pass
        try:
            process.close()
        except Exception:
            pass

    @staticmethod
    def _share_array(data: Any) -> tuple[shared_memory.SharedMemory, dict[str, Any]]:
        """Copy ROI data into shared memory so Windows spawn stays responsive."""

        if isinstance(data, np.ndarray) and data.dtype in (np.float32, np.float64) and data.flags["C_CONTIGUOUS"]:
            array = data
        elif isinstance(data, np.ndarray) and data.dtype in (np.float32, np.float64):
            array = np.ascontiguousarray(data)
        else:
            array = np.ascontiguousarray(data, dtype=np.float32)

        shm = shared_memory.SharedMemory(create=True, size=array.nbytes)
        shared_array = np.ndarray(array.shape, dtype=array.dtype, buffer=shm.buf)
        shared_array[...] = array
        return shm, {
            "name": shm.name,
            "shape": array.shape,
            "dtype": array.dtype.str,
        }

    @staticmethod
    def _terminate_process(process: Any) -> None:
        if process is None:
            return
        try:
            if process.is_alive():
                process.terminate()
        except Exception:
            pass

    @staticmethod
    def _close_conn(conn: Any) -> None:
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass

    @staticmethod
    def _cleanup_shared_memory(block: shared_memory.SharedMemory | None) -> None:
        if block is None:
            return
        try:
            block.close()
        except Exception:
            pass
        try:
            block.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
