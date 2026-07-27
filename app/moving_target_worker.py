from __future__ import annotations

import os
import sys


_FROZEN_DLL_DIRECTORY_HANDLES: list[object] = []


def _register_frozen_dll_directories() -> None:
    """Make frozen NumPy/SEP runtime DLLs visible in spawn children on Windows."""

    if not getattr(sys, "frozen", False) or not hasattr(os, "add_dll_directory"):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    for path in (
        meipass,
        os.path.join(meipass, "Library", "bin"),
        os.path.join(meipass, "numpy.libs"),
        os.path.join(meipass, "numpy", ".libs"),
    ):
        if os.path.isdir(path):
            try:
                handle = os.add_dll_directory(path)
            except OSError:
                pass
            else:
                # add_dll_directory() removes the search path when its handle is
                # closed.  Keep the handles alive for the lifetime of this
                # module, including in multiprocessing spawn children.
                _FROZEN_DLL_DIRECTORY_HANDLES.append(handle)


_register_frozen_dll_directories()

import dataclasses
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.contracts import ROISelection
from ..core.moving_targets import MovingTargetParameters, resolve_frame_times


_NO_RESULT = object()


def _moving_target_subprocess_entry(
    stack_spec: dict[str, Any],
    seconds: np.ndarray,
    roi_dict: dict[str, int],
    params_dict: dict[str, Any],
    time_source: str,
    warnings: tuple[str, ...],
    result_conn: Any,
) -> None:
    """Map the private ROI stack, run the core pipeline, and stream progress."""

    stack: np.memmap | None = None
    try:
        from ..core.moving_targets import detect_moving_targets

        stack = np.memmap(
            stack_spec["path"],
            dtype=np.dtype(stack_spec["dtype"]),
            mode="r+",
            shape=tuple(stack_spec["shape"]),
        )

        def progress(completed: int, total: int, message: str) -> None:
            result_conn.send(("progress", (completed, total, message)))

        result = detect_moving_targets(
            stack,
            seconds,
            roi=ROISelection(**roi_dict),
            parameters=MovingTargetParameters(**params_dict),
            time_source=time_source,
            warnings=warnings,
            in_place=True,
            progress_callback=progress,
        )
        stack.flush()
        result_conn.send(("ok", result))
    except BaseException as exc:  # noqa: BLE001 - child errors must cross the pipe
        try:
            result_conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except Exception:
            pass
    finally:
        if stack is not None:
            try:
                stack.flush()
            except Exception:
                pass
            mapping = getattr(stack, "_mmap", None)
            if mapping is not None:
                try:
                    mapping.close()
                except Exception:
                    pass
        try:
            result_conn.close()
        except Exception:
            pass


class MovingTargetWorker(QObject):
    """QThread adapter that runs SEP-heavy sequence analysis in a spawn child."""

    result_ready = Signal(int, object)
    detection_error = Signal(int, str)
    progress = Signal(int, int, int, str)
    finished = Signal(int)

    _POLL_TIMEOUT_SECONDS = 0.05
    _TERMINATE_JOIN_TIMEOUT_SECONDS = 0.5
    _KILL_JOIN_TIMEOUT_SECONDS = 0.5

    def __init__(
        self,
        *,
        request_id: int,
        frames: list[Any],
        roi: ROISelection,
        parameters: MovingTargetParameters,
        fallback_cadence_seconds: float,
        prefer_header_times: bool,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.frames = list(frames)
        self.roi = roi
        self.parameters = parameters
        self.fallback_cadence_seconds = float(fallback_cadence_seconds)
        self.prefer_header_times = bool(prefer_header_times)
        self._process: Any = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self._terminate_process(self._process)

    def _is_cancelled(self) -> bool:
        try:
            interrupted = QThread.currentThread().isInterruptionRequested()
        except Exception:
            interrupted = False
        return self._cancelled or interrupted

    @Slot()
    def run(self) -> None:
        process: Any = None
        parent_conn: Any = None
        child_conn: Any = None
        temp_directory: TemporaryDirectory | None = None
        result_payload: Any = _NO_RESULT
        error_detail: str | None = None
        try:
            if self._is_cancelled():
                return
            frame_count, height, width = self._validate_inputs()
            validated = self.parameters.validated(frame_count, (height, width))
            headers = [getattr(frame, "header", None) for frame in self.frames]
            seconds, time_source, warnings = resolve_frame_times(
                headers,
                fallback_cadence_seconds=self.fallback_cadence_seconds,
                prefer_header_times=self.prefer_header_times,
            )

            temp_directory = TemporaryDirectory(prefix="astroview-moving-targets-")
            temp_dir = temp_directory.name
            try:
                stack_path = Path(temp_dir) / "roi-stack.float32"
                stack = np.memmap(
                    stack_path,
                    dtype=np.float32,
                    mode="w+",
                    shape=(frame_count, height, width),
                )
                try:
                    for index, frame in enumerate(self.frames):
                        if self._is_cancelled():
                            return
                        data = np.asarray(getattr(frame, "data", None))
                        crop = data[
                            self.roi.y0 : self.roi.y0 + self.roi.height,
                            self.roi.x0 : self.roi.x0 + self.roi.width,
                        ]
                        stack[index] = np.asarray(crop, dtype=np.float32)
                        self.progress.emit(
                            self.request_id,
                            index + 1,
                            frame_count,
                            f"Preparing ROI frame {index + 1}/{frame_count}",
                        )
                    stack.flush()
                finally:
                    mapping = getattr(stack, "_mmap", None)
                    if mapping is not None:
                        mapping.close()
            except Exception:
                # Keep the memmap mapping lifetime visibly inside this block;
                # process and temporary-directory cleanup is centralized below.
                raise

            if self._is_cancelled():
                return
            ctx = multiprocessing.get_context("spawn")
            parent_conn, child_conn = ctx.Pipe(duplex=False)
            stack_spec = {
                "path": str(stack_path),
                "shape": (frame_count, height, width),
                "dtype": np.dtype(np.float32).str,
            }
            process = ctx.Process(
                target=_moving_target_subprocess_entry,
                args=(
                    stack_spec,
                    seconds,
                    dataclasses.asdict(self.roi),
                    dataclasses.asdict(validated),
                    time_source,
                    warnings,
                    child_conn,
                ),
                daemon=True,
            )
            self._process = process
            process.start()
            child_conn.close()
            child_conn = None

            outcome: tuple[str, Any] | None = None
            while True:
                if self._is_cancelled():
                    return
                try:
                    if parent_conn.poll(self._POLL_TIMEOUT_SECONDS):
                        message = parent_conn.recv()
                        if message[0] == "progress":
                            completed, total, detail = message[1]
                            self.progress.emit(
                                self.request_id,
                                int(completed),
                                int(total),
                                str(detail),
                            )
                            continue
                        outcome = message
                        break
                    if not process.is_alive():
                        if parent_conn.poll():
                            outcome = parent_conn.recv()
                        break
                except (EOFError, OSError):
                    break

            if self._is_cancelled():
                return
            if outcome is None:
                raise RuntimeError("Moving-target subprocess exited without posting a result")
            kind, payload = outcome
            if kind != "ok":
                raise RuntimeError(str(payload))
            result_payload = payload
        except Exception as exc:
            error_detail = str(exc)
        finally:
            self._close_conn(parent_conn)
            self._close_conn(child_conn)
            process_stopped = self._cleanup_process(process)
            self._process = None
            if temp_directory is not None:
                if process_stopped:
                    try:
                        temp_directory.cleanup()
                    except Exception as exc:
                        if error_detail is None:
                            error_detail = f"Could not clean up moving-target temporary data: {exc}"
                else:
                    # Never let TemporaryDirectory's finalizer remove a memmap
                    # that may still be open in a surviving Windows child.
                    self._detach_temp_directory_finalizer(temp_directory)
                    if error_detail is None:
                        error_detail = (
                            "Moving-target subprocess could not be stopped; "
                            f"temporary data was preserved at {temp_directory.name}"
                        )
            if not self._is_cancelled():
                if error_detail is not None:
                    self.detection_error.emit(self.request_id, error_detail)
                elif result_payload is not _NO_RESULT:
                    self.result_ready.emit(self.request_id, result_payload)
            self.finished.emit(self.request_id)

    def _validate_inputs(self) -> tuple[int, int, int]:
        if len(self.frames) < 5:
            raise ValueError("Moving-target detection requires at least 5 loaded frames.")
        expected_shape: tuple[int, int] | None = None
        for index, frame in enumerate(self.frames):
            data = getattr(frame, "data", None)
            if data is None:
                raise ValueError(f"Frame {index + 1} has no image data.")
            array = np.asarray(data)
            if array.ndim != 2:
                raise ValueError(f"Frame {index + 1} is not a 2D image.")
            if np.issubdtype(array.dtype, np.complexfloating):
                raise ValueError(f"Frame {index + 1} contains complex-valued image data.")
            shape = (int(array.shape[0]), int(array.shape[1]))
            if expected_shape is None:
                expected_shape = shape
            elif shape != expected_shape:
                raise ValueError("All moving-target input frames must have the same shape.")
        assert expected_shape is not None
        full_height, full_width = expected_shape
        if (
            self.roi.x0 < 0
            or self.roi.y0 < 0
            or self.roi.width <= 0
            or self.roi.height <= 0
            or self.roi.x0 + self.roi.width > full_width
            or self.roi.y0 + self.roi.height > full_height
        ):
            raise ValueError("Moving-target ROI is empty or outside the common frame bounds.")
        return len(self.frames), self.roi.height, self.roi.width

    def _cleanup_process(self, process: Any) -> bool:
        """Stop and reap *process*, returning whether it is safe to delete its files."""

        if process is None:
            return True
        try:
            process.join(timeout=self._TERMINATE_JOIN_TIMEOUT_SECONDS)
        except (AssertionError, ValueError):
            # An unstarted or already-closed Process has no live child.
            pass
        except Exception:
            pass
        if self._process_is_alive(process):
            try:
                process.terminate()
            except Exception:
                pass
            try:
                process.join(timeout=self._TERMINATE_JOIN_TIMEOUT_SECONDS)
            except Exception:
                pass
        if self._process_is_alive(process):
            killed = False
            try:
                process.kill()
                killed = True
            except Exception:
                pass
            if killed:
                try:
                    # Once kill() succeeds, wait for the OS process handle to be
                    # signalled instead of racing a fixed timeout against
                    # TemporaryDirectory cleanup on Windows.
                    process.join()
                except Exception:
                    pass
            else:
                try:
                    process.join(timeout=self._KILL_JOIN_TIMEOUT_SECONDS)
                except Exception:
                    pass
        if self._process_is_alive(process):
            return False
        try:
            process.close()
        except Exception:
            pass
        return True

    @staticmethod
    def _process_is_alive(process: Any) -> bool:
        try:
            return bool(process.is_alive())
        except (AssertionError, ValueError):
            return False
        except Exception:
            # Unknown state is not proof that it is safe to remove the memmap.
            return True

    @staticmethod
    def _detach_temp_directory_finalizer(temp_directory: TemporaryDirectory) -> None:
        finalizer = getattr(temp_directory, "_finalizer", None)
        if finalizer is not None:
            try:
                finalizer.detach()
            except Exception:
                pass

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


__all__ = ["MovingTargetWorker", "_moving_target_subprocess_entry"]
