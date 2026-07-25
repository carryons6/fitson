from __future__ import annotations

import unittest

from astroview import (
    APP_RELEASES_API_URL,
    APP_RELEASES_URL,
    APP_REPOSITORY,
    APP_TAGS_API_URL,
)


class TestApplicationMetadata(unittest.TestCase):
    def test_update_channel_matches_authoritative_repository(self) -> None:
        self.assertEqual(APP_REPOSITORY, "carryons6/fitson")
        self.assertEqual(
            APP_RELEASES_API_URL,
            "https://api.github.com/repos/carryons6/fitson/releases/latest",
        )
        self.assertEqual(
            APP_TAGS_API_URL,
            "https://api.github.com/repos/carryons6/fitson/tags?per_page=1",
        )
        self.assertEqual(
            APP_RELEASES_URL,
            "https://github.com/carryons6/fitson/releases",
        )


if __name__ == "__main__":
    unittest.main()
