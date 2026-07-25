from __future__ import annotations

import math
import socket
import unittest
from unittest.mock import Mock, patch

from astroview.core.catalog_service import (
    CatalogQuery,
    CatalogQueryCancelled,
    GAIA_TAP_URL,
    MAX_CATALOG_RESPONSE_BYTES,
    build_gaia_adql,
    parse_gaia_csv,
    query_gaia,
)


class _Response:
    def __init__(self, payload: bytes, *, content_length: str | None = None) -> None:
        self.payload = payload
        self.status = 200
        self.reason = "OK"
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


class TestCatalogService(unittest.TestCase):
    def test_query_validation_normalizes_ra_and_rejects_nonfinite_values(self) -> None:
        query = CatalogQuery(ra_deg=721.0, dec_deg=-20.0, radius_deg=0.5).validated()
        self.assertEqual(query.ra_deg, 1.0)

        with self.assertRaisesRegex(ValueError, "finite"):
            CatalogQuery(math.nan, 0.0, 0.1).validated()
        with self.assertRaisesRegex(ValueError, "radius"):
            CatalogQuery(10.0, 0.0, 2.1).validated()
        with self.assertRaisesRegex(ValueError, "Declination"):
            CatalogQuery(10.0, 91.0, 0.1).validated()

    def test_adql_contains_only_validated_numeric_parameters(self) -> None:
        adql = build_gaia_adql(
            CatalogQuery(ra_deg=123.45, dec_deg=-54.3, radius_deg=0.25, max_rows=42, faint_limit_mag=18.5)
        )
        self.assertIn("SELECT TOP 42", adql)
        self.assertIn("gaiadr3.gaia_source", adql)
        self.assertIn("123.4500000000", adql)
        self.assertIn("phot_g_mean_mag <= 18.5000", adql)

    def test_parse_csv_skips_invalid_rows_and_bounds_result(self) -> None:
        payload = (
            "source_id,ra,dec,phot_g_mean_mag,phot_bp_mean_mag,phot_rp_mean_mag\n"
            "1,180.0,45.0,12.3,13.0,11.8\n"
            "2,nan,45.0,10.0,,\n"
            "3,181.0,95.0,11.0,,\n"
            "4,182.0,44.0,,12.0,11.0\n"
        )
        sources = parse_gaia_csv(payload, max_rows=2)
        self.assertEqual([source.source_id for source in sources], ["1", "4"])
        self.assertEqual(sources[0].g_mag, 12.3)
        self.assertIsNone(sources[1].g_mag)

    def test_parse_csv_rejects_missing_columns_and_oversize_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "required columns"):
            parse_gaia_csv("id,x,y\n1,2,3\n")
        with self.assertRaisesRegex(ValueError, "download size"):
            parse_gaia_csv(b"x" * (MAX_CATALOG_RESPONSE_BYTES + 1))

    def test_query_uses_fixed_https_endpoint_and_bounded_read(self) -> None:
        payload = b"source_id,ra,dec\n1,180,45\n"
        response = _Response(payload)
        opener = Mock()
        opener.open.return_value = response
        factory = Mock(return_value=opener)

        sources = query_gaia(
            CatalogQuery(180.0, 45.0, 0.1, max_rows=5),
            opener_factory=factory,
        )

        self.assertEqual(len(sources), 1)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, GAIA_TAP_URL)
        self.assertEqual(request.method, "POST")
        self.assertIn(b"gaiadr3.gaia_source", request.data)
        opener.open.assert_called_once_with(request, timeout=12.0)

    def test_query_rejects_oversize_content_length_before_read(self) -> None:
        response = _Response(b"", content_length=str(MAX_CATALOG_RESPONSE_BYTES + 1))
        opener = Mock()
        opener.open.return_value = response
        with self.assertRaisesRegex(ValueError, "download size"):
            query_gaia(
                CatalogQuery(180.0, 45.0, 0.1),
                opener_factory=Mock(return_value=opener),
            )

    def test_query_observes_cancellation_between_bounded_chunks(self) -> None:
        response = _Response(b"x" * (64 * 1024))
        opener = Mock()
        opener.open.return_value = response
        checks = iter((False, False, True))
        observed: list[object | None] = []
        with self.assertRaises(CatalogQueryCancelled):
            query_gaia(
                CatalogQuery(180.0, 45.0, 0.1),
                opener_factory=Mock(return_value=opener),
                cancel_check=lambda: next(checks),
                response_observer=observed.append,
            )
        self.assertIs(observed[0], response)
        self.assertIsNone(observed[-1])

    def test_query_enforces_total_read_deadline(self) -> None:
        response = _Response(b"")
        response.read = Mock(side_effect=socket.timeout())
        opener = Mock()
        opener.open.return_value = response
        with patch("astroview.core.catalog_service.time.monotonic", side_effect=[0.0, 0.5, 1.1]):
            with self.assertRaisesRegex(TimeoutError, "total time limit"):
                query_gaia(
                    CatalogQuery(180.0, 45.0, 0.1),
                    timeout=1.0,
                    opener_factory=Mock(return_value=opener),
                )


if __name__ == "__main__":
    unittest.main()
