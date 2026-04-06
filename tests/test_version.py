from __future__ import annotations

import unittest
from pathlib import Path

import sys

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview import __version__
from astroview.version import read_version


class TestVersion(unittest.TestCase):
    def test_package_version_matches_version_file(self) -> None:
        self.assertEqual(__version__, read_version())


if __name__ == "__main__":
    unittest.main()
