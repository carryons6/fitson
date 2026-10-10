from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astroview.app import theme


class TestThemeIconResources(unittest.TestCase):
    def test_all_theme_arrows_resolve_inside_the_packaged_resource_directory(self) -> None:
        icon_dir = theme._theme_icon_dir().resolve()

        for key, expected_name in theme._ARROW_RESOURCE_NAMES.items():
            with self.subTest(key=key):
                resolved = theme._arrow_path(*key)
                self.assertIsNotNone(resolved)
                resource = Path(str(resolved)).resolve()
                self.assertEqual(resource.name, expected_name)
                self.assertEqual(resource.parent, icon_dir)
                self.assertTrue(resource.is_file())

    def test_unknown_theme_arrow_is_rejected(self) -> None:
        with self.assertLogs(theme.logger, level="WARNING"):
            result = theme._arrow_path("sideways", "#ffffff")

        self.assertIsNone(result)

    def test_missing_packaged_arrow_disables_that_icon(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with patch.object(theme, "_theme_icon_dir", return_value=Path(root)):
                with self.assertLogs(theme.logger, level="WARNING"):
                    result = theme._arrow_path("up", "#1f2430")

        self.assertIsNone(result)

    def test_spinbox_stylesheet_disables_icons_when_resource_is_missing(self) -> None:
        with patch.object(theme, "_arrow_path", return_value=None):
            stylesheet = theme._spinbox_qss("#1", "#2", "#3", "#4", "#5")

        self.assertEqual(stylesheet.count("image: none;"), 3)
        self.assertNotIn("url(None)", stylesheet)


if __name__ == "__main__":
    unittest.main()
