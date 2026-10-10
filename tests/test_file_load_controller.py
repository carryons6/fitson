from __future__ import annotations

import os
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from astroview.app.file_load_controller import FileLoadController, FrameLoadRequest


class _Emitter(QObject):
    file_loaded = Signal(object, object)
    file_error = Signal(str, str)
    progress = Signal(int, int, str)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        self.file_loaded.emit("loaded frame", None)
        self.progress.emit(1, 1, "frame.fits")
        self.finished.emit()


class TestFileLoadController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _active(self, *, running: bool = True) -> tuple[FileLoadController, Mock, Mock]:
        controller = FileLoadController(join_wait_ms=123)
        thread, worker = Mock(), Mock()
        thread.isRunning.return_value = running
        controller.task.activate(thread, worker)
        return controller, thread, worker

    def test_repeated_requests_replace_pending_until_old_thread_retires(self) -> None:
        controller, thread, worker = self._active()
        launches, queued = [], []
        controller.launch_requested.connect(launches.append)
        controller.request_queued.connect(queued.append)
        first = FrameLoadRequest(("first.fits",))
        newest = FrameLoadRequest(("newest.fits",), hdu_index=2, append=True)
        controller.start(first)
        controller.start(newest)
        self.assertEqual(launches, [])
        self.assertEqual(queued, [first, newest])
        self.assertIs(controller.pending, newest)
        self.assertIs(controller.task.thread, thread)

        thread.isRunning.return_value = False
        controller.handle_thread_finished(1, thread, worker)
        controller.handle_thread_finished(1, thread, worker)
        self.assertEqual(launches, [newest])
        self.assertIsNone(controller.pending)

    def test_request_after_thread_exit_replaces_unprocessed_pending_intent(self) -> None:
        controller, thread, worker = self._active(running=False)
        launches = []
        controller.launch_requested.connect(launches.append)
        controller.pending = FrameLoadRequest(("older.fits",))
        newest = FrameLoadRequest(("newest.fits",))
        controller.start(newest)
        controller.handle_thread_finished(1, thread, worker)
        self.assertEqual(launches, [newest])

    def test_cancellation_rejects_all_queued_callbacks_and_keeps_timed_out_worker(self) -> None:
        controller, thread, worker = self._active()
        received = []
        controller.frame_accepted.connect(lambda *args: received.append(args))
        controller.error_accepted.connect(lambda *args: received.append(args))
        controller.progress_accepted.connect(lambda *args: received.append(args))
        controller.load_finished.connect(lambda: received.append("finished"))
        controller.cancel_feedback_pending = True
        self.assertFalse(controller.stop(wait=True))
        controller.handle_loaded(1, worker, "late frame", None)
        controller.handle_error(1, worker, "late.fits", "failure")
        controller.handle_progress(1, worker, 1, 1, "late.fits")
        controller.handle_finished(1, worker)
        self.assertEqual(received, [])
        self.assertIs(controller.task.thread, thread)
        thread.wait.assert_called_once_with(123)

        cancelled = []
        controller.load_cancelled.connect(lambda: cancelled.append(True))
        thread.isRunning.return_value = False
        controller.handle_thread_finished(1, thread, worker)
        self.assertEqual(cancelled, [True])
        self.assertFalse(controller.cancel_feedback_pending)

    def test_worker_finished_does_not_free_slot_before_thread_finished(self) -> None:
        controller, thread, worker = self._active()
        finished = []
        controller.load_finished.connect(lambda: finished.append(True))
        controller.handle_finished(1, worker)
        self.assertEqual(finished, [True])
        self.assertIs(controller.task.thread, thread)
        self.assertFalse(controller.launch(FrameLoadRequest(("another.fits",))))

    def test_closing_discards_pending_without_launch_or_cancel_feedback(self) -> None:
        controller, thread, worker = self._active()
        controller.pending = FrameLoadRequest(("pending.fits",))
        controller.cancel_feedback_pending = True
        events = []
        controller.launch_requested.connect(lambda request: events.append(request))
        controller.load_cancelled.connect(lambda: events.append("cancelled"))
        controller.idle.connect(lambda: events.append("idle"))
        controller.closing = True
        controller.stop()
        thread.isRunning.return_value = False
        controller.handle_thread_finished(1, thread, worker)
        controller.start(FrameLoadRequest(("late.fits",)))
        self.assertEqual(events, ["idle"])
        self.assertIsNone(controller.pending)

    def test_stale_callbacks_and_cleanup_cannot_affect_replacement(self) -> None:
        controller, old_thread, old_worker = self._active(running=False)
        controller.handle_thread_finished(1, old_thread, old_worker)
        thread, worker = Mock(), Mock()
        thread.isRunning.return_value = True
        controller.task.activate(thread, worker)
        frames = []
        controller.frame_accepted.connect(lambda data, preview: frames.append(data))
        controller.handle_loaded(1, old_worker, "old", None)
        controller.handle_thread_finished(1, old_thread, old_worker)
        controller.handle_loaded(2, worker, "new", None)
        self.assertEqual(frames, ["new"])
        self.assertIs(controller.task.thread, thread)

    def test_launch_passes_snapshot_options_and_allocates_request_identity(self) -> None:
        controller = FileLoadController()
        request = FrameLoadRequest(("a.fits", "b.fits"), hdu_index=2, append=True)
        with patch("astroview.app.file_load_controller.QThread.start", autospec=True):
            self.assertTrue(controller.launch(request, preview_max_dimension=3072, source_group_start=5))
        worker = controller.task.worker
        thread = controller.task.thread
        self.assertEqual(worker.paths, ["a.fits", "b.fits"])
        self.assertEqual(worker.hdu_index, 2)
        self.assertEqual(worker.preview_max_dimension, 3072)
        self.assertEqual(worker.source_group_start, 5)
        self.assertTrue(controller.request_is_current(1, worker))
        controller.handle_thread_finished(1, thread, worker)
        controller.deleteLater()

    def test_real_worker_callbacks_are_delivered_on_gui_thread(self) -> None:
        controller = FileLoadController(worker_factory=lambda *args, **kwargs: _Emitter())
        handler_threads, frames, retired = [], [], []
        controller.frame_accepted.connect(
            lambda data, preview: (handler_threads.append(QThread.currentThread()), frames.append(data))
        )
        controller.idle.connect(lambda: retired.append(True))
        controller.launch(FrameLoadRequest(("frame.fits",)))
        try:
            deadline = time.monotonic() + 3
            while not retired and time.monotonic() < deadline:
                self._app.processEvents()
                time.sleep(0.001)
            self.assertEqual(frames, ["loaded frame"])
            self.assertEqual(handler_threads, [self._app.thread()])
            self.assertEqual(retired, [True])
            self.assertIsNone(controller.task.thread)
        finally:
            controller.closing = True
            controller.stop(wait=True)
            controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
