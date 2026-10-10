from __future__ import annotations

import unittest
from unittest.mock import Mock

from astroview.app.task_lifecycle import TaskLifecycle


class TestTaskLifecycle(unittest.TestCase):
    def test_cancel_invalidates_results_but_does_not_release_physical_slot(self) -> None:
        task = TaskLifecycle()
        thread, worker = Mock(), Mock()
        thread.isRunning.return_value = True
        request_id = task.activate(thread, worker)
        self.assertTrue(task.accepts(request_id, worker))

        self.assertFalse(task.request_stop(wait_ms=123))
        self.assertFalse(task.accepts(request_id, worker))
        self.assertIs(task.thread, thread)
        thread.wait.assert_called_once_with(123)
        self.assertFalse(task.retire(request_id, thread, worker))
        with self.assertRaises(RuntimeError):
            task.activate(Mock(), Mock())

        thread.isRunning.return_value = False
        self.assertTrue(task.retire(request_id, thread, worker))
        self.assertIsNone(task.thread)
        self.assertEqual(task.activate(Mock(), Mock()), request_id + 1)

    def test_stale_retirement_cannot_release_a_new_task(self) -> None:
        task = TaskLifecycle()
        old_thread, old_worker = Mock(), Mock()
        old_thread.isRunning.return_value = False
        old_request = task.activate(old_thread, old_worker)
        self.assertTrue(task.retire(old_request, old_thread, old_worker))
        thread, worker = Mock(), Mock()
        thread.isRunning.return_value = False
        request = task.activate(thread, worker)

        self.assertFalse(task.retire(old_request, old_thread, old_worker))
        self.assertFalse(task.retire(request, old_thread, worker))
        self.assertFalse(task.retire(request, thread, old_worker))
        self.assertTrue(task.accepts(request, worker))
        self.assertFalse(task.accepts(old_request, old_worker))
        self.assertIs(task.thread, thread)

    def test_deferred_qt_deletion_still_allows_matching_retirement(self) -> None:
        task = TaskLifecycle()
        thread, worker = Mock(), Mock()
        thread.isRunning.side_effect = RuntimeError("QObject already deleted")
        request = task.activate(thread, worker)
        self.assertTrue(task.request_stop())
        self.assertTrue(task.retire(request, thread, worker))


if __name__ == "__main__":
    unittest.main()
