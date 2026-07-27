from __future__ import annotations

import csv
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np


REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.core.contracts import ROISelection
from astroview.core.moving_targets import (
    MovingTargetError,
    MovingTargetLimitError,
    MovingTargetParameters,
    _CandidateTrack,
    _SpatialIndex,
    _find_tracks,
    _recover_tracks,
    _registered_common_bounds,
    _registered_translation,
    detect_moving_targets,
    export_moving_targets_csv,
    resolve_frame_times,
)


def _add_gaussian(image: np.ndarray, x: float, y: float, amplitude: float, sigma: float = 1.15) -> None:
    radius = 4
    x0 = max(0, int(np.floor(x)) - radius)
    x1 = min(image.shape[1], int(np.floor(x)) + radius + 2)
    y0 = max(0, int(np.floor(y)) - radius)
    y1 = min(image.shape[0], int(np.floor(y)) + radius + 2)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    image[y0:y1, x0:x1] += amplitude * np.exp(
        -((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma**2)
    )


def _synthetic_sequence() -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    rng = np.random.default_rng(1024)
    height, width = 128, 160
    seconds = np.array([0.0, 1.0, 2.3, 3.5, 4.8, 6.0, 7.4, 8.7, 10.0])
    static = [(x, y) for y in (18, 38, 58, 94, 112) for x in (16, 40, 64, 88, 112, 136)]
    vx, vy = 3.0, -0.25
    stack = np.empty((len(seconds), height, width), dtype=np.float32)
    for index, time_value in enumerate(seconds):
        dx = 0.18 * index
        dy = -0.11 * index
        image = rng.normal(100.0, 0.8, size=(height, width)).astype(np.float32)
        for star_index, (x, y) in enumerate(static):
            _add_gaussian(image, x + dx, y + dy, 75.0 + (star_index % 4) * 8.0)
        _add_gaussian(
            image,
            24.0 + vx * time_value + dx,
            76.0 + vy * time_value + dy,
            130.0,
            sigma=1.2,
        )
        stack[index] = image
    return stack, seconds, (vx, vy)


_TEST_OBJECT_DTYPE = np.dtype(
    [
        ("x", np.float64),
        ("y", np.float64),
        ("flux", np.float64),
        ("peak", np.float64),
    ]
)


def _test_objects(points: list[tuple[float, float]] | np.ndarray) -> np.ndarray:
    positions = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    objects = np.zeros(len(positions), dtype=_TEST_OBJECT_DTYPE)
    if len(objects):
        objects["x"] = positions[:, 0]
        objects["y"] = positions[:, 1]
        objects["flux"] = 100.0
        objects["peak"] = 20.0
    return objects


def _linear_track_candidates(
    bases: tuple[float, ...],
) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]:
    seconds = np.arange(5, dtype=np.float64)
    positions = [
        np.asarray([(base + time_value, 8.0) for base in bases], dtype=np.float64)
        for time_value in seconds
    ]
    objects = [_test_objects(points) for points in positions]
    return seconds, positions, objects


class TestMovingTargetCore(unittest.TestCase):
    def test_frame_times_prefer_date_avg_and_warn_on_fixed_fallback(self) -> None:
        headers = [
            {"DATE-AVG": f"2026-01-01T00:00:0{index}.000"}
            for index in range(5)
        ]
        seconds, source, warnings = resolve_frame_times(
            headers,
            fallback_cadence_seconds=2.5,
        )
        np.testing.assert_allclose(seconds, np.arange(5), atol=1e-5)
        self.assertEqual(source, "DATE-AVG")
        self.assertEqual(warnings, ())

        seconds, source, warnings = resolve_frame_times(
            [{}, {}, {}, {}, {}],
            fallback_cadence_seconds=2.5,
        )
        np.testing.assert_allclose(seconds, np.arange(5) * 2.5)
        self.assertEqual(source, "Fixed cadence (2.5 s)")
        self.assertTrue(warnings)
        with self.assertRaises(ValueError):
            resolve_frame_times([{}] * 5, fallback_cadence_seconds=True)

        observed = [
            {"DATE-OBS": f"2026-01-01T00:00:0{index}.000", "EXPTIME": 2.0}
            for index in range(5)
        ]
        seconds, source, _ = resolve_frame_times(observed, fallback_cadence_seconds=1.0)
        np.testing.assert_allclose(seconds, np.arange(5), atol=1e-5)
        self.assertEqual(source, "DATE-OBS")

        split_observed = [
            {
                "DATE-OBS": "2026-01-01",
                "TIME-OBS": f"00:00:0{index}.000",
                "EXPTIME": 2.0,
            }
            for index in range(5)
        ]
        seconds, source, _ = resolve_frame_times(
            split_observed,
            fallback_cadence_seconds=1.0,
        )
        np.testing.assert_allclose(seconds, np.arange(5), atol=1e-5)
        self.assertEqual(source, "DATE-OBS")

    def test_valid_header_times_that_are_out_of_order_or_duplicated_are_rejected(self) -> None:
        cases = {
            "out of order": (0, 1, 3, 2, 4),
            "duplicated": (0, 1, 2, 2, 4),
        }
        for label, offsets in cases.items():
            with self.subTest(label=label):
                headers = [
                    {"DATE-AVG": f"2026-01-01T00:00:0{offset}.000"}
                    for offset in offsets
                ]
                with self.assertRaisesRegex(
                    MovingTargetError,
                    r"(?i)strictly increasing|duplicat|out of order",
                ):
                    resolve_frame_times(headers, fallback_cadence_seconds=2.5)

    def test_mixed_average_and_observation_start_time_semantics_are_rejected(self) -> None:
        headers = [
            {"DATE-AVG": "2026-01-01T00:00:00.000"},
            {"DATE-OBS": "2026-01-01T00:00:00.000", "EXPTIME": 2.0},
            {"DATE-AVG": "2026-01-01T00:00:02.000"},
            {"DATE-OBS": "2026-01-01T00:00:02.000", "EXPTIME": 2.0},
            {"DATE-AVG": "2026-01-01T00:00:04.000"},
        ]

        with self.assertRaisesRegex(
            MovingTargetError,
            r"(?i)mixed|semantic|AVG.*OBS|OBS.*AVG",
        ):
            resolve_frame_times(headers, fallback_cadence_seconds=1.0)

    def test_observation_times_cannot_mix_start_and_exposure_midpoint(self) -> None:
        headers = [
            {"DATE-OBS": f"2026-01-01T00:00:0{index}.000", "EXPTIME": 2.0}
            for index in range(5)
        ]
        headers[2] = {"DATE-OBS": "2026-01-01T00:00:02.000"}
        with self.assertRaisesRegex(MovingTargetError, r"(?i)exposure.*start|midpoint"):
            resolve_frame_times(headers, fallback_cadence_seconds=1.0)

    def test_registration_translation_uses_current_minus_reference_sign(self) -> None:
        image = np.zeros((20, 24), dtype=np.float32)
        image[9, 13] = 1.0  # current source is reference (10, 8) + (3, 1)
        registered = _registered_translation(image, 3.0, 1.0)
        y, x = np.unravel_index(int(np.argmax(registered)), registered.shape)
        self.assertEqual((x, y), (10, 8))

    def test_large_radius_spatial_query_scans_actual_points_not_empty_cells(self) -> None:
        points = np.array([[0.0, 0.0], [10.0, 5.0], [20.0, 10.0]], dtype=np.float64)
        index = _SpatialIndex(points, cell_size=0.25)
        self.assertEqual(index.neighbors((0.0, 0.0), 1.0e12), [0, 1, 2])

    def test_registration_common_bounds_exclude_reflected_borders(self) -> None:
        shifts = np.array([[-20.0, 5.0], [0.0, 0.0], [8.0, -14.0]], dtype=np.float64)
        self.assertEqual(
            _registered_common_bounds(shifts, width=100, height=80),
            (20.0, 14.0, 92.0, 75.0),
        )

    def test_resource_limits_fail_before_analysis(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 5"):
            MovingTargetParameters().validated(4, (100, 100))
        with self.assertRaises(MovingTargetLimitError):
            MovingTargetParameters(max_roi_pixels=100).validated(5, (16, 16))

    def test_total_source_limit_is_enforced_across_frames(self) -> None:
        self.assertIn(
            "max_total_sources",
            MovingTargetParameters.__dataclass_fields__,
            "MovingTargetParameters must expose a total source-catalog budget.",
        )
        parameters = MovingTargetParameters(
            max_sources_per_frame=20,
            max_total_sources=50,
        )
        objects = _test_objects(
            [(x, y) for y in (2.0, 6.0, 10.0, 14.0) for x in (2.0, 5.0, 8.0, 11.0, 14.0)]
        )
        empty_positions = [np.empty((0, 2), dtype=np.float64) for _ in range(5)]
        empty_objects = [_test_objects([]) for _ in range(5)]

        def fake_extract(image, _threshold, *, max_sources):
            self.assertEqual(max_sources, 20)
            return np.zeros_like(image, dtype=np.float32), objects.copy(), 1.0

        with (
            patch(
                "astroview.core.moving_targets._extract_frame_sources",
                side_effect=fake_extract,
            ),
            patch(
                "astroview.core.moving_targets._robust_catalog_shift",
                return_value=(0.0, 0.0, 20, 0.05),
            ),
            patch(
                "astroview.core.moving_targets._persistent_static_catalog",
                return_value=(np.empty((0, 2), dtype=np.float64), 5),
            ),
            patch(
                "astroview.core.moving_targets._temporal_median",
                return_value=np.zeros((16, 16), dtype=np.float32),
            ),
            patch(
                "astroview.core.moving_targets._difference_candidates",
                return_value=(empty_positions, empty_objects, (0, 0, 0, 0, 0)),
            ),
            patch("astroview.core.moving_targets._find_tracks", return_value=[]),
            patch("astroview.core.moving_targets._recover_tracks", return_value=()),
        ):
            with self.assertRaisesRegex(
                MovingTargetLimitError,
                r"(?i)total.*source|source.*total|source.*across.*sequence|across.*sequence.*source",
            ):
                detect_moving_targets(
                    np.zeros((5, 16, 16), dtype=np.float32),
                    np.arange(5, dtype=np.float64),
                    parameters=parameters,
                )

    def test_raw_track_limit_stops_duplicate_fits_before_deduplication(self) -> None:
        self.assertIn(
            "max_raw_tracks",
            MovingTargetParameters.__dataclass_fields__,
            "MovingTargetParameters must bound the raw fitted-track list.",
        )
        self.assertIn("max_unique_tracks", MovingTargetParameters.__dataclass_fields__)
        seconds, positions, objects = _linear_track_candidates((4.0,))
        parameters = MovingTargetParameters(
            min_track_hits=5,
            min_track_speed=0.5,
            max_track_speed=2.0,
            max_track_rms=0.1,
            track_tolerance=0.25,
            min_displacement=1.0,
            max_track_seeds=1_000,
            max_raw_tracks=2,
            max_unique_tracks=100,
            max_output_tracks=100,
        ).validated(5, (64, 64))

        with self.assertRaisesRegex(
            MovingTargetLimitError,
            r"(?i)raw.*track|track.*raw",
        ):
            _find_tracks(
                seconds,
                positions,
                objects,
                parameters,
                cancel_check=None,
            )

    def test_unique_track_limit_is_enforced_during_deduplication(self) -> None:
        self.assertIn(
            "max_unique_tracks",
            MovingTargetParameters.__dataclass_fields__,
            "MovingTargetParameters must bound the deduplicated-track list.",
        )
        self.assertIn("max_raw_tracks", MovingTargetParameters.__dataclass_fields__)
        seconds, positions, objects = _linear_track_candidates((4.0, 24.0, 44.0))
        parameters = MovingTargetParameters(
            min_track_hits=5,
            min_track_speed=0.5,
            max_track_speed=2.0,
            max_track_rms=0.1,
            track_tolerance=0.25,
            min_displacement=1.0,
            max_track_seeds=1_000,
            max_raw_tracks=1_000,
            max_unique_tracks=2,
            max_output_tracks=100,
        ).validated(5, (64, 64))

        with self.assertRaisesRegex(
            MovingTargetLimitError,
            r"(?i)unique.*track|deduplicat.*track|track.*unique",
        ):
            _find_tracks(
                seconds,
                positions,
                objects,
                parameters,
                cancel_check=None,
            )

    def test_recovery_assigns_each_nonstatic_sep_source_to_only_one_track(self) -> None:
        seconds = np.arange(5, dtype=np.float64)
        frame_indices = np.arange(5, dtype=np.int64)
        tracks = [
            _CandidateTrack(
                frame_indices=frame_indices,
                detection_indices=np.zeros(5, dtype=np.int64),
                x0=x0,
                y0=10.0,
                vx=0.0,
                vy=0.0,
                rms=0.1,
                median_snr=5.0,
            )
            for x0 in (10.0, 10.4)
        ]
        sources = [_test_objects([(10.1, 10.0)]) for _ in seconds]
        recovered = _recover_tracks(
            tracks,
            sources,
            np.zeros((5, 2), dtype=np.float64),
            seconds,
            ROISelection(0, 0, 32, 32),
            1.0,
            np.empty((0, 2), dtype=np.float64),
            1.0,
        )

        measured = np.stack([track.measured_mask for track in recovered])
        np.testing.assert_array_equal(np.sum(measured, axis=0), np.ones(5, dtype=np.int64))

        static_recovered = _recover_tracks(
            tracks[:1],
            sources,
            np.zeros((5, 2), dtype=np.float64),
            seconds,
            ROISelection(0, 0, 32, 32),
            1.0,
            np.array([[10.1, 10.0]], dtype=np.float64),
            1.0,
        )
        self.assertFalse(np.any(static_recovered[0].measured_mask))

    def test_registration_rejects_excessive_rms(self) -> None:
        self._assert_registration_quality_rejected(
            registration=(0.1, -0.1, 20, 1.5),
            error_pattern=r"(?i)registration.*rms|rms.*registration",
        )

    def test_registration_rejects_insufficient_match_fraction(self) -> None:
        self._assert_registration_quality_rejected(
            registration=(0.1, -0.1, 10, 0.05),
            error_pattern=r"(?i)registration.*match|match.*registration",
        )

    def _assert_registration_quality_rejected(
        self,
        *,
        registration: tuple[float, float, int, float],
        error_pattern: str,
    ) -> None:
        required_fields = {"registration_max_rms", "registration_min_match_fraction"}
        self.assertTrue(
            required_fields.issubset(MovingTargetParameters.__dataclass_fields__),
            "MovingTargetParameters must expose RMS and match-fraction registration guards.",
        )
        parameters = MovingTargetParameters(
            registration_source_limit=20,
            registration_max_rms=0.25,
            registration_min_match_fraction=0.75,
        )
        catalog = _test_objects(
            [(x, y) for y in (2.0, 6.0, 10.0, 14.0) for x in (2.0, 5.0, 8.0, 11.0, 14.0)]
        )
        empty_positions = [np.empty((0, 2), dtype=np.float64) for _ in range(5)]
        empty_objects = [_test_objects([]) for _ in range(5)]

        def fake_extract(image, _threshold, *, max_sources):
            self.assertGreaterEqual(max_sources, len(catalog))
            return np.zeros_like(image, dtype=np.float32), catalog.copy(), 1.0

        with (
            patch(
                "astroview.core.moving_targets._extract_frame_sources",
                side_effect=fake_extract,
            ),
            patch(
                "astroview.core.moving_targets._robust_catalog_shift",
                return_value=registration,
            ),
            patch(
                "astroview.core.moving_targets._persistent_static_catalog",
                return_value=(np.empty((0, 2), dtype=np.float64), 5),
            ),
            patch(
                "astroview.core.moving_targets._temporal_median",
                return_value=np.zeros((16, 16), dtype=np.float32),
            ),
            patch(
                "astroview.core.moving_targets._difference_candidates",
                return_value=(empty_positions, empty_objects, (0, 0, 0, 0, 0)),
            ),
            patch("astroview.core.moving_targets._find_tracks", return_value=[]),
            patch("astroview.core.moving_targets._recover_tracks", return_value=()),
        ):
            with self.assertRaisesRegex(MovingTargetError, error_pattern):
                detect_moving_targets(
                    np.zeros((5, 16, 16), dtype=np.float32),
                    np.arange(5, dtype=np.float64),
                    parameters=parameters,
                )

    def test_synthetic_registered_sequence_recovers_linear_mover(self) -> None:
        stack, seconds, truth = _synthetic_sequence()
        original = stack.copy()
        result = detect_moving_targets(
            stack,
            seconds,
            roi=ROISelection(x0=20, y0=30, width=stack.shape[2], height=stack.shape[1]),
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
            time_source="synthetic",
        )
        np.testing.assert_array_equal(stack, original)
        self.assertGreaterEqual(len(result.tracks), 1)
        best = min(result.tracks, key=lambda track: abs(track.vx - truth[0]) + abs(track.vy - truth[1]))
        self.assertAlmostEqual(best.vx, truth[0], delta=0.2)
        self.assertAlmostEqual(best.vy, truth[1], delta=0.2)
        self.assertGreaterEqual(best.hits, 6)
        self.assertLess(best.rms, 0.8)
        self.assertGreater(float(best.positions[0, 0]), 20.0)
        self.assertGreater(float(best.positions[0, 1]), 30.0)

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "moving.csv"
            export_moving_targets_csv(result, path)
            with path.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), len(result.tracks) * result.frame_count)
            self.assertEqual(rows[0]["TimeSource"], "synthetic")


if __name__ == "__main__":
    unittest.main()
