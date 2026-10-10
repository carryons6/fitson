"""Exercise the real moving-target spawn path with disposable synthetic data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from threading import Event, Timer

import numpy as np
from PySide6.QtCore import Qt

from ..core.contracts import ROISelection
from ..core.fits_data import FITSData
from ..core.moving_targets import MovingTargetParameters
from .moving_target_worker import MovingTargetWorker


def _synthetic_frames() -> list[FITSData]:
    """A small deterministic registered star field with one moving source."""

    rng = np.random.default_rng(1024)
    height, width = 128, 160
    seconds = (0.0, 1.0, 2.3, 3.5, 4.8, 6.0, 7.4, 8.7, 10.0)
    static = [(x, y) for y in (18, 38, 58, 94, 112) for x in (16, 40, 64, 88, 112, 136)]
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frames = []

    def add_star(image: np.ndarray, x: float, y: float, amplitude: float, sigma: float = 1.15) -> None:
        x0, x1 = max(0, int(np.floor(x)) - 4), min(width, int(np.floor(x)) + 6)
        y0, y1 = max(0, int(np.floor(y)) - 4), min(height, int(np.floor(y)) + 6)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        image[y0:y1, x0:x1] += amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))

    for index, seconds_value in enumerate(seconds):
        dx, dy = 0.18 * index, -0.11 * index
        image = rng.normal(100.0, 0.8, size=(height, width)).astype(np.float32)
        for star_index, (x, y) in enumerate(static):
            add_star(image, x + dx, y + dy, 75.0 + (star_index % 4) * 8.0)
        add_star(image, 24.0 + 3.0 * seconds_value + dx, 76.0 - 0.25 * seconds_value + dy, 130.0, 1.2)
        frames.append(FITSData(
            path=f"smoke-frame-{index}.fits",
            data=image,
            # FITS DATE values use implicit UTC, without an ISO timezone suffix.
            header={"DATE-AVG": (epoch + timedelta(seconds=seconds_value)).strftime("%Y-%m-%dT%H:%M:%S.%f")},
        ))
    return frames


def run_moving_target_spawn_smoke(*, timeout_seconds: float = 30.0) -> None:
    """Validate child imports, IPC, detection, identities, and worker cleanup.

    The watchdog cancels the worker and terminates its child after the deadline.
    The build runner independently applies a hard process-tree timeout, including
    cleanup, so broken frozen bootstrap code cannot hang a release build.
    """

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Moving-target smoke timeout must be positive and finite.")
    request_id = 731
    frames = _synthetic_frames()
    worker = MovingTargetWorker(
        request_id=request_id,
        frames=frames,
        roi=ROISelection(0, 0, 160, 128),
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
    results, errors, progress_ids, finished = [], [], [], []
    direct = Qt.ConnectionType.DirectConnection
    worker.result_ready.connect(lambda identity, result: results.append((identity, result)), direct)
    worker.detection_error.connect(lambda identity, detail: errors.append((identity, detail)), direct)
    worker.progress.connect(lambda identity, _done, _total, _detail: progress_ids.append(identity), direct)
    worker.finished.connect(finished.append, direct)
    timed_out = Event()

    def cancel_overdue_worker() -> None:
        timed_out.set()
        worker.cancel()

    watchdog = Timer(timeout_seconds, cancel_overdue_worker)
    watchdog.daemon = True
    watchdog.start()
    try:
        worker.run()
    finally:
        watchdog.cancel()
        watchdog.join(timeout=1.0)
    if timed_out.is_set():
        raise TimeoutError(f"Moving-target spawn smoke exceeded {timeout_seconds:g} seconds.")
    if errors:
        raise RuntimeError(f"Moving-target spawn smoke failed: {errors!r}")
    if finished != [request_id] or len(results) != 1 or results[0][0] != request_id:
        raise RuntimeError("Moving-target spawn smoke returned missing or incorrect request identities.")
    if not progress_ids or any(identity != request_id for identity in progress_ids):
        raise RuntimeError("Moving-target spawn smoke returned missing or incorrect progress identities.")
    result = results[0][1]
    if result.frame_count != len(frames) or not any(
        track.hits >= 6 and abs(track.vx - 3.0) < 0.75 and abs(track.vy + 0.25) < 0.75
        for track in result.tracks
    ):
        raise RuntimeError("Moving-target spawn smoke did not recover the synthetic moving source.")
