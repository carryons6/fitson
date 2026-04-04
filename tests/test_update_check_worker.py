from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.update_check_worker import (
    APP_RELEASES_API_URL,
    APP_TAGS_API_URL,
    UpdateCheckWorker,
    compare_versions,
    fetch_latest_version_info,
    normalize_version,
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

    def test_worker_reports_update_available(self) -> None:
        results = []
        worker = UpdateCheckWorker("1.2.3")
        worker.result_ready.connect(results.append)

        with patch("astroview.app.update_check_worker.fetch_latest_version_info", return_value=("1.3.0", "https://example.com/release")):
            worker.run()

        self.assertEqual(results[0].status, "update_available")
        self.assertEqual(results[0].latest_version, "1.3.0")


if __name__ == "__main__":
    unittest.main()
