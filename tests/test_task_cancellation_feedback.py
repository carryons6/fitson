from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from astroview.app.main_window import MainWindow


class TestTaskCancellationFeedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = QSettings(str(Path(temporary.name) / 'cancellation.ini'), QSettings.Format.IniFormat)
        with patch('astroview.app.main_window.QSettings', return_value=settings):
            self.window = MainWindow()
            self.window.initialize(apply_startup_request=False)
        self.addCleanup(self._close_window)

    def _close_window(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_sep_cancel_after_physical_exit_does_not_recreate_cancelling_activity(self):
        thread, worker = Mock(), Mock()
        thread.isRunning.return_value = False
        controller = self.window._sep_controller
        request_id = controller.task.activate(thread, worker)
        self.window._set_status_activity(kind='sep', text='Running SEP', cancellable=True)

        self.window._handle_status_bar_cancel_requested()

        self.assertIsNone(controller.task.thread)
        self.assertIsNone(self.window._status_activity_kind)
        self.assertEqual(self.window.app_status_bar.currentMessage(), self.window.tr('SEP extraction cancelled.'))
        # This queued signal arrives after synchronous cancellation retired the
        # thread. It cannot be relied on to clear a newly created activity.
        controller.handle_thread_finished(request_id, thread, worker)
        self.assertIsNone(self.window._status_activity_kind)

    def test_sep_cancel_keeps_cancelling_activity_until_running_thread_retires(self):
        thread, worker = Mock(), Mock()
        thread.isRunning.return_value = True
        controller = self.window._sep_controller
        request_id = controller.task.activate(thread, worker)
        self.window._set_status_activity(kind='sep', text='Running SEP', cancellable=True)

        self.window._handle_status_bar_cancel_requested()

        self.assertIs(controller.task.thread, thread)
        self.assertEqual(self.window._status_activity_kind, 'sep')
        self.assertFalse(controller.task.results_enabled)
        worker.cancel.assert_called_once_with()
        thread.isRunning.return_value = False
        controller.handle_thread_finished(request_id, thread, worker)
        self.assertIsNone(controller.task.thread)
        self.assertIsNone(self.window._status_activity_kind)


if __name__ == '__main__':
    unittest.main()
