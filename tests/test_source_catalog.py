from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from core.source_catalog import SourceCatalog, SourceRecord


class _FakeAngle:
    def __init__(self, deg: float) -> None:
        self.deg = deg


class _FakeSkyCoord:
    def __init__(self, ra_deg: float, dec_deg: float) -> None:
        self.ra = _FakeAngle(ra_deg)
        self.dec = _FakeAngle(dec_deg)


class _FakeWCS:
    def pixel_to_world(self, x: float, y: float) -> _FakeSkyCoord:
        return _FakeSkyCoord(100.0 + x / 10.0, 20.0 + y / 10.0)


class _BrokenWCS:
    def pixel_to_world(self, x: float, y: float):
        raise RuntimeError("conversion failed")


class TestSourceCatalog(unittest.TestCase):
    def test_from_sep_objects_applies_offsets_rounding_and_wcs(self) -> None:
        objects = {
            "x": np.array([1.234]),
            "y": np.array([5.678]),
            "npix": np.array([9]),
            "flux": np.array([12.345]),
            "peak": np.array([6.789]),
            "a": np.array([1.23456]),
            "b": np.array([0.98765]),
            "theta": np.array([0.123456]),
            "flag": np.array([2]),
        }

        catalog = SourceCatalog.from_sep_objects(
            objects,
            x_offset=10,
            y_offset=20,
            wcs=_FakeWCS(),
            background_rms=2.0,
        )

        self.assertEqual(len(catalog), 1)
        record = catalog[0]
        self.assertEqual(record.source_id, 1)
        self.assertEqual(record.x, 11.23)
        self.assertEqual(record.y, 25.68)
        self.assertEqual(record.ra, "101.123400")
        self.assertEqual(record.dec, "22.567800")
        self.assertEqual(record.flux, 12.35)
        self.assertEqual(record.peak, 6.79)
        self.assertEqual(record.snr, 2.06)
        self.assertEqual(record.npix, 9)
        self.assertEqual(record.background_rms, 2.0)
        self.assertEqual(record.a, 1.235)
        self.assertEqual(record.b, 0.988)
        self.assertEqual(record.theta, 0.1235)
        self.assertEqual(record.flag, 2)

    def test_from_sep_objects_falls_back_when_wcs_conversion_fails(self) -> None:
        objects = {
            "x": np.array([1.0]),
            "y": np.array([2.0]),
            "npix": np.array([4]),
            "flux": np.array([3.0]),
            "peak": np.array([4.0]),
            "a": np.array([1.0]),
            "b": np.array([1.0]),
            "theta": np.array([0.0]),
            "flag": np.array([0]),
        }

        catalog = SourceCatalog.from_sep_objects(objects, wcs=_BrokenWCS())

        self.assertEqual(catalog[0].ra, "-")
        self.assertEqual(catalog[0].dec, "-")

    def test_collection_helpers_and_to_rows(self) -> None:
        catalog = SourceCatalog()
        record = SourceRecord(source_id=7, x=1.5, y=2.5, flux=9.0, peak=5.0, snr=3.456, flag=1)

        catalog.append(record)

        self.assertEqual(len(catalog), 1)
        self.assertIs(catalog.get(0), record)
        self.assertIsNone(catalog.get(3))
        self.assertEqual(list(catalog), [record])
        self.assertEqual(
            catalog.to_rows(),
            [{
                "ID": 7,
                "X": 1.5,
                "Y": 2.5,
                "RA": "-",
                "Dec": "-",
                "Flux": 9.0,
                "Peak": 5.0,
                "SNR": 3.46,
                "NPix": 0,
                "BkgRMS": 0.0,
                "A": 0.0,
                "B": 0.0,
                "Theta": 0.0,
                "Flag": 1,
            }],
        )

        catalog.clear()
        self.assertEqual(len(catalog), 0)

    def test_to_rows_can_filter_visible_columns(self) -> None:
        catalog = SourceCatalog(
            records=[SourceRecord(source_id=1, x=10.0, y=20.0, flux=3.0, peak=4.0, snr=5.0)]
        )

        rows = catalog.to_rows(["ID", "Flux", "SNR"])

        self.assertEqual(rows, [{"ID": 1, "Flux": 3.0, "SNR": 5.0}])

    def test_to_csv_writes_header_and_rows(self) -> None:
        catalog = SourceCatalog(
            records=[SourceRecord(source_id=1, x=10.0, y=20.0, ra="1.0", dec="2.0", flux=3.0, peak=4.0)]
        )

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "catalog.csv"
            catalog.to_csv(str(path))

            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ID"], "1")
        self.assertEqual(rows[0]["X"], "10.0")
        self.assertEqual(rows[0]["RA"], "1.0")
        self.assertEqual(rows[0]["Peak"], "4.0")

    def test_to_csv_can_write_selected_columns_only(self) -> None:
        catalog = SourceCatalog(
            records=[SourceRecord(source_id=1, x=10.0, y=20.0, flux=3.0, peak=4.0, snr=5.0)]
        )

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "catalog.csv"
            catalog.to_csv(str(path), columns=["ID", "Flux", "SNR"])

            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows, [{"ID": "1", "Flux": "3.0", "SNR": "5.0"}])

if __name__ == "__main__":
    unittest.main()
