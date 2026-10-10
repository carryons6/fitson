from __future__ import annotations

import os
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from astroview.app import release_smoke
from astroview import main as main_module


class _FakeWorker(QObject):
    result_ready = Signal(int, object)
    detection_error = Signal(int, str)
    progress = Signal(int, int, int, str)
    finished = Signal(int)

    def __init__(self, *, behavior: str, **options) -> None:
        super().__init__()
        self.behavior = behavior
        self.request_id = options["request_id"]
        self.cancelled = Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        identity = self.request_id
        if self.behavior == "timeout":
            if not self.cancelled.wait(2.0):
                raise RuntimeError("Smoke watchdog did not cancel the worker.")
        elif self.behavior == "error":
            self.detection_error.emit(identity, "missing frozen dependency")
        else:
            reported = identity + 1 if self.behavior == "wrong_identity" else identity
            self.progress.emit(reported, 1, 1, "done")
            tracks = () if self.behavior == "no_track" else (SimpleNamespace(hits=9, vx=3.0, vy=-0.25),)
            self.result_ready.emit(reported, SimpleNamespace(frame_count=9, tracks=tracks))
        self.finished.emit(identity)


class TestReleaseSpawnSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_real_spawn_pipeline_recovers_synthetic_track(self) -> None:
        release_smoke.run_moving_target_spawn_smoke(timeout_seconds=30)

    def test_spawn_errors_identity_mismatch_and_missing_track_fail_validation(self) -> None:
        for behavior, message in (
            ("error", "missing frozen dependency"),
            ("wrong_identity", "request identities"),
            ("no_track", "synthetic moving source"),
        ):
            with self.subTest(behavior=behavior):
                with patch.object(release_smoke, "MovingTargetWorker", side_effect=lambda **options: _FakeWorker(behavior=behavior, **options)):
                    with self.assertRaisesRegex(RuntimeError, message):
                        release_smoke.run_moving_target_spawn_smoke()

    def test_watchdog_cancels_unresponsive_worker_and_reports_timeout(self) -> None:
        workers = []

        def factory(**options):
            worker = _FakeWorker(behavior="timeout", **options)
            workers.append(worker)
            return worker

        with patch.object(release_smoke, "MovingTargetWorker", side_effect=factory):
            with self.assertRaisesRegex(TimeoutError, "exceeded"):
                release_smoke.run_moving_target_spawn_smoke(timeout_seconds=0.01)
        self.assertTrue(workers[0].cancelled.is_set())

    def test_main_smoke_runs_spawn_check_before_reporting_success(self) -> None:
        with patch.object(release_smoke, "run_moving_target_spawn_smoke") as spawn:
            with patch.object(main_module, "apply_theme"):
                with patch.object(main_module, "_write_smoke_report") as report:
                    self.assertEqual(main_module.run_smoke_test(), 0)
        spawn.assert_called_once_with()
        self.assertIn("RUNNING moving-target spawn", [call.args[0] for call in report.call_args_list])
        self.assertTrue(report.call_args.args[0].startswith("OK "))

    def test_main_smoke_reports_spawn_failure_instead_of_success(self) -> None:
        with patch.object(release_smoke, "run_moving_target_spawn_smoke", side_effect=RuntimeError("spawn failed")):
            with patch.object(main_module, "apply_theme"):
                with patch.object(main_module, "_write_smoke_report") as report:
                    self.assertEqual(main_module.run_smoke_test(), 1)
        self.assertTrue(report.call_args.args[0].startswith("FAILED\n"))
        self.assertIn("spawn failed", report.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
