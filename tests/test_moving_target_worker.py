from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app import moving_target_worker as worker_module
from astroview.app.moving_target_worker import MovingTargetWorker
from astroview.core.contracts import ROISelection
from astroview.core.fits_data import FITSData
from astroview.core.moving_targets import MovingTargetParameters
from tests.test_moving_targets import _synthetic_sequence


class _FakeConnection:
    def __init__(
        self,
        *,
        events: list[str],
        messages: tuple[tuple[str, object], ...] = (),
        wake_event: threading.Event | None = None,
        name: str,
    ) -> None:
        self._events = events
        self._messages = list(messages)
        self._wake_event = wake_event
        self._name = name

    def poll(self, timeout: float | None = None) -> bool:
        if self._messages:
            return True
        if timeout and self._wake_event is not None:
            self._wake_event.wait(timeout)
        return bool(self._messages)

    def recv(self) -> tuple[str, object]:
        if not self._messages:
            raise EOFError
        return self._messages.pop(0)

    def close(self) -> None:
        self._events.append(f"{self._name}_close")


class _FakeProcess:
    def __init__(
        self,
        *,
        events: list[str],
        started: threading.Event,
        wake_event: threading.Event,
        stop_on_terminate: bool,
    ) -> None:
        self._events = events
        self._started = started
        self._wake_event = wake_event
        self._stop_on_terminate = stop_on_terminate
        self._alive = False
        self._killed = False

    def start(self) -> None:
        self._alive = True
        self._events.append("process_start")
        self._started.set()

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self._events.append("join_blocking" if timeout is None else "join_timed")
        if timeout is None and self._killed:
            self._alive = False

    def terminate(self) -> None:
        self._events.append("process_terminate")
        self._wake_event.set()
        if self._stop_on_terminate:
            self._alive = False

    def kill(self) -> None:
        self._events.append("process_kill")
        self._killed = True
        self._wake_event.set()

    def close(self) -> None:
        self._events.append("process_close")


class _FakeSpawnContext:
    def __init__(
        self,
        *,
        process: _FakeProcess,
        parent_conn: _FakeConnection,
        child_conn: _FakeConnection,
    ) -> None:
        self._process = process
        self._parent_conn = parent_conn
        self._child_conn = child_conn

    def Pipe(self, *, duplex: bool) -> tuple[_FakeConnection, _FakeConnection]:
        if duplex:
            raise AssertionError("Worker must use a one-way result pipe")
        return self._parent_conn, self._child_conn

    def Process(self, **_kwargs: object) -> _FakeProcess:
        return self._process


class _TrackingTemporaryDirectory:
    def __init__(self, *, events: list[str], process: _FakeProcess, prefix: str) -> None:
        self._events = events
        self._process = process
        self._inner = tempfile.TemporaryDirectory(prefix=prefix)
        self.name = self._inner.name
        self.cleaned_while_process_alive = False

    def cleanup(self) -> None:
        self.cleaned_while_process_alive = self._process.is_alive()
        self._events.append("temp_cleanup")
        self._inner.cleanup()


class TestMovingTargetWorker(unittest.TestCase):
    @staticmethod
    def _small_worker(request_id: int) -> MovingTargetWorker:
        frames = [
            FITSData(
                path=f"frame-{index}.fits",
                data=np.zeros((16, 16), dtype=np.float32),
                header={},
            )
            for index in range(5)
        ]
        return MovingTargetWorker(
            request_id=request_id,
            frames=frames,
            roi=ROISelection(0, 0, 16, 16),
            parameters=MovingTargetParameters(),
            fallback_cadence_seconds=1.0,
            prefer_header_times=True,
        )

    @staticmethod
    def _fake_runtime(
        *,
        stop_on_terminate: bool,
        messages: tuple[tuple[str, object], ...] = (),
    ) -> tuple[
        list[str],
        threading.Event,
        _FakeProcess,
        _FakeSpawnContext,
        list[_TrackingTemporaryDirectory],
        object,
    ]:
        events: list[str] = []
        started = threading.Event()
        wake_event = threading.Event()
        process = _FakeProcess(
            events=events,
            started=started,
            wake_event=wake_event,
            stop_on_terminate=stop_on_terminate,
        )
        parent_conn = _FakeConnection(
            events=events,
            messages=messages,
            wake_event=wake_event,
            name="parent_conn",
        )
        child_conn = _FakeConnection(events=events, name="child_conn")
        context = _FakeSpawnContext(
            process=process,
            parent_conn=parent_conn,
            child_conn=child_conn,
        )
        directories: list[_TrackingTemporaryDirectory] = []

        def create_temp_directory(*, prefix: str) -> _TrackingTemporaryDirectory:
            directory = _TrackingTemporaryDirectory(
                events=events,
                process=process,
                prefix=prefix,
            )
            directories.append(directory)
            return directory

        return events, started, process, context, directories, create_temp_directory

    def test_frozen_dll_directory_handles_are_retained(self) -> None:
        handles = [object() for _ in range(4)]
        retained: list[object] = []
        with (
            patch.object(worker_module.sys, "frozen", True, create=True),
            patch.object(worker_module.sys, "_MEIPASS", "C:/frozen", create=True),
            patch.object(worker_module.os.path, "isdir", return_value=True),
            patch.object(
                worker_module.os,
                "add_dll_directory",
                side_effect=handles,
                create=True,
            ),
            patch.object(worker_module, "_FROZEN_DLL_DIRECTORY_HANDLES", retained),
        ):
            worker_module._register_frozen_dll_directories()

        self.assertEqual(retained, handles)

    def test_precancelled_worker_only_finishes(self) -> None:
        worker = MovingTargetWorker(
            request_id=7,
            frames=[],
            roi=ROISelection(0, 0, 16, 16),
            parameters=MovingTargetParameters(),
            fallback_cadence_seconds=1.0,
            prefer_header_times=True,
        )
        results: list[object] = []
        errors: list[str] = []
        finished: list[int] = []
        worker.result_ready.connect(lambda _request, result: results.append(result))
        worker.detection_error.connect(lambda _request, detail: errors.append(detail))
        worker.finished.connect(finished.append)
        worker.cancel()
        worker.run()
        self.assertEqual(results, [])
        self.assertEqual(errors, [])
        self.assertEqual(finished, [7])

    def test_running_cancel_reaps_child_before_cleaning_temp_directory(self) -> None:
        worker = self._small_worker(8)
        events, started, process, context, directories, temp_factory = self._fake_runtime(
            stop_on_terminate=False
        )
        run_failures: list[BaseException] = []

        def run_worker() -> None:
            try:
                worker.run()
            except BaseException as exc:  # pragma: no cover - assertion reports it
                run_failures.append(exc)

        with (
            patch.object(worker_module.multiprocessing, "get_context", return_value=context),
            patch.object(worker_module, "TemporaryDirectory", side_effect=temp_factory),
        ):
            run_thread = threading.Thread(target=run_worker)
            run_thread.start()
            try:
                self.assertTrue(started.wait(2.0), "fake subprocess did not start")
                worker.cancel()
            finally:
                if run_thread.is_alive() and not worker._cancelled:
                    worker.cancel()
                run_thread.join(2.0)

        self.assertFalse(run_thread.is_alive())
        self.assertFalse(process.is_alive())
        self.assertEqual(run_failures, [])
        self.assertEqual(len(directories), 1)
        self.assertFalse(directories[0].cleaned_while_process_alive)
        self.assertFalse(Path(directories[0].name).exists())
        self.assertLess(events.index("process_kill"), events.index("join_blocking"))
        self.assertLess(events.index("join_blocking"), events.index("temp_cleanup"))

    def test_child_error_reaps_child_and_removes_temp_directory(self) -> None:
        worker = self._small_worker(9)
        events, _started, process, context, directories, temp_factory = self._fake_runtime(
            stop_on_terminate=True,
            messages=(("error", "Synthetic child failure"),),
        )
        errors: list[str] = []
        finished: list[int] = []
        worker.detection_error.connect(lambda _request, detail: errors.append(detail))
        worker.finished.connect(finished.append)

        with (
            patch.object(worker_module.multiprocessing, "get_context", return_value=context),
            patch.object(worker_module, "TemporaryDirectory", side_effect=temp_factory),
        ):
            worker.run()

        self.assertFalse(process.is_alive())
        self.assertEqual(errors, ["Synthetic child failure"])
        self.assertEqual(finished, [9])
        self.assertEqual(len(directories), 1)
        self.assertFalse(directories[0].cleaned_while_process_alive)
        self.assertFalse(Path(directories[0].name).exists())
        self.assertLess(events.index("process_terminate"), events.index("process_close"))
        self.assertLess(events.index("process_close"), events.index("temp_cleanup"))

    def test_worker_runs_spawn_pipeline_and_reports_request_identity(self) -> None:
        stack, seconds, _ = _synthetic_sequence()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        frames = [
            FITSData(
                path=f"frame-{index}.fits",
                data=stack[index],
                header={"DATE-AVG": (start + timedelta(seconds=float(value))).isoformat()},
            )
            for index, value in enumerate(seconds)
        ]
        worker = MovingTargetWorker(
            request_id=11,
            frames=frames,
            roi=ROISelection(0, 0, stack.shape[2], stack.shape[1]),
            parameters=MovingTargetParameters(
                detection_threshold=3.0,
                difference_threshold=3.0,
                min_track_hits=6,
                min_track_speed=1.0,
                max_track_speed=10.0,
                max_track_rms=0.8,
                track_tolerance=2.0,
                recovery_tolerance=3.0,
                registration_source_limit=100,
                static_match_radius=1.8,
                static_mask_radius=3.0,
                edge_margin=5,
                max_difference_area=100,
            ),
            fallback_cadence_seconds=1.0,
            prefer_header_times=True,
        )
        results: list[tuple[int, object]] = []
        errors: list[str] = []
        progress: list[tuple[int, int, int, str]] = []
        finished: list[int] = []
        worker.result_ready.connect(lambda request, result: results.append((request, result)))
        worker.detection_error.connect(lambda _request, detail: errors.append(detail))
        worker.progress.connect(lambda request, done, total, detail: progress.append((request, done, total, detail)))
        worker.finished.connect(finished.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(finished, [11])
        self.assertEqual(results[0][0], 11)
        self.assertTrue(results[0][1].tracks)
        self.assertTrue(progress)
        self.assertTrue(all(entry[0] == 11 for entry in progress))


if __name__ == "__main__":
    unittest.main()
