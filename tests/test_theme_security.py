from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from astroview.app import theme


class TestThemeIconCacheSecurity(unittest.TestCase):
    def test_private_cache_directories_are_unpredictable_and_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            first_context, first = theme._create_private_arrow_cache(Path(root))
            second_context, second = theme._create_private_arrow_cache(Path(root))
            try:
                self.assertNotEqual(first, second)
                self.assertEqual(first.parent, Path(root))
                self.assertEqual(second.parent, Path(root))
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(second.stat().st_mode), 0o700)
            finally:
                first_context.cleanup()
                second_context.cleanup()

    def test_spinbox_stylesheet_disables_icons_when_cache_is_unwritable(self) -> None:
        with patch.object(theme, "_arrow_path", return_value=None):
            stylesheet = theme._spinbox_qss("#1", "#2", "#3", "#4", "#5")

        self.assertEqual(stylesheet.count("image: none;"), 3)
        self.assertNotIn("url(None)", stylesheet)

    def test_arrow_path_rejects_failed_pixmap_save(self) -> None:
        pixmap = Mock()
        pixmap.save.return_value = False
        cache_key = ("up", "#ffffff")
        theme._arrow_paths_cache.pop(cache_key, None)
        with tempfile.TemporaryDirectory() as root:
            with patch.object(theme, "_get_arrow_cache_dir", return_value=Path(root)):
                with patch.object(theme, "_arrow_pixmap", return_value=pixmap):
                    with self.assertLogs(theme.logger, level="WARNING"):
                        result = theme._arrow_path("up", "#ffffff")

        self.assertIsNone(result)
        self.assertNotIn(cache_key, theme._arrow_paths_cache)


if __name__ == "__main__":
    unittest.main()
