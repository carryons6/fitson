from __future__ import annotations

import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview import __version__
from astroview.app.update_check_worker import (
    APP_RELEASES_API_URL,
    APP_TAGS_API_URL,
    APP_RELEASES_URL,
    UpdateCheckWorker,
    build_release_url,
    compare_versions,
    fetch_json,
    fetch_latest_version_info,
    normalize_version,
    version_key,
)


class TestUpdateCheckWorker(unittest.TestCase):
    def test_normalize_version_strips_leading_v(self) -> None:
        self.assertEqual(normalize_version("v1.2.3"), "1.2.3")

    def test_compare_versions_handles_multi_digit_segments(self) -> None:
        self.assertLess(compare_versions("1.2.3", "1.2.10"), 0)

    def test_fetch_latest_version_info_prefers_release_tag(self) -> None:
        with patch("astroview.app.update_check_worker.fetch_json") as fetch_mock:
            fetch_mock.return_value = {"tag_name": "v1.3.0", "html_url": "https://example.com/release"}

            latest, url = fetch_latest_version_info()

        fetch_mock.assert_called_once_with(APP_RELEASES_API_URL)
        self.assertEqual(latest, "1.3.0")
        self.assertEqual(url, "https://example.com/release")

    def test_fetch_latest_version_info_falls_back_to_tags(self) -> None:
        with patch("astroview.app.update_check_worker.fetch_json") as fetch_mock:
            fetch_mock.side_effect = [
                HTTPError(APP_RELEASES_API_URL, 404, "Not Found", hdrs=None, fp=None),
                [{"name": "v1.2.5"}],
            ]

            latest, url = fetch_latest_version_info()

        self.assertEqual(fetch_mock.call_args_list[1].args[0], APP_TAGS_API_URL)
        self.assertEqual(latest, "1.2.5")
        self.assertTrue(url.endswith("/tag/v1.2.5"))

    def test_build_release_url_points_to_github_release_tag(self) -> None:
        self.assertEqual(
            build_release_url(f"v{__version__}"),
            f"{APP_RELEASES_URL}/tag/v{__version__}",
        )

    def test_fetch_json_uses_proxyless_opener(self) -> None:
        response = Mock()
        response.status = 200
        response.reason = "OK"
        response.headers = {}
        response.read.return_value = f'{{"tag_name":"v{__version__}"}}'.encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        opener = Mock()
        opener.open.return_value = response

        with patch("astroview.app.update_check_worker.build_opener", return_value=opener) as opener_factory:
            payload = fetch_json(APP_RELEASES_API_URL)

        opener_factory.assert_called_once()
        opener.open.assert_called_once()
        self.assertEqual(payload["tag_name"], f"v{__version__}")

    def test_worker_reports_update_available(self) -> None:
        results = []
        worker = UpdateCheckWorker(__version__)
        worker.result_ready.connect(results.append)
        current_parts = list(version_key(__version__))
        current_parts[-1] += 1
        latest_version = ".".join(str(part) for part in current_parts)

        with patch(
            "astroview.app.update_check_worker.fetch_latest_version_info",
            return_value=(latest_version, "https://example.com/release"),
        ):
            worker.run()

        self.assertEqual(results[0].status, "update_available")
        self.assertEqual(results[0].latest_version, latest_version)


if __name__ == "__main__":
    unittest.main()
