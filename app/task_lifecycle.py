"""Small, Qt-independent bookkeeping for one physical background task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TaskLifecycle:
    """Keep result validity separate from ownership of a running worker.

    Invalidating callbacks must not free the physical slot. Only retirement of
    the matching thread/worker pair releases it after that thread has stopped.
    Scheduling policy and user-facing cancellation feedback belong to callers.
    """

    request_id: int = 0
    active_request_id: int | None = None
    thread: Any = None
    worker: Any = None
    results_enabled: bool = False

    @property
    def running(self) -> bool:
        if self.thread is None:
            return False
        try:
            return bool(self.thread.isRunning())
        except RuntimeError:
            # Qt may have delivered deferred deletion before queued cleanup.
            return False

    def activate(self, thread: Any, worker: Any) -> int:
        if self.thread is not None:
            raise RuntimeError("Retire the previous task before starting another.")
        self.request_id += 1
        self.active_request_id = self.request_id
        self.thread = thread
        self.worker = worker
        self.results_enabled = True
        return self.request_id

    def accepts(self, request_id: int, worker: Any) -> bool:
        return bool(
            self.results_enabled
            and request_id == self.active_request_id
            and worker is self.worker
        )

    def retire(self, request_id: int | None, thread: Any, worker: Any) -> bool:
        if (
            request_id != self.active_request_id
            or thread is not self.thread
            or worker is not self.worker
            or self.running
        ):
            return False
        self.active_request_id = None
        self.thread = None
        self.worker = None
        self.results_enabled = False
        return True

    def request_stop(self, *, wait_ms: int | None = None) -> bool:
        """Reject queued callbacks immediately; retain ownership until retire."""

        self.results_enabled = False
        thread = self.thread
        if thread is None:
            return True
        if self.running:
            thread.requestInterruption()
            thread.quit()
        if wait_ms is not None and self.running:
            thread.wait(max(0, int(wait_ms)))
        return not self.running
