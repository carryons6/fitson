from __future__ import annotations

import argparse
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview import main as main_module


class TestMainEntry(unittest.TestCase):
    def test_main_defers_startup_file_open_until_after_window_show(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = argparse.Namespace(path="demo.fits", hdu=None)
        app = Mock()
        app.exec.return_value = 0
        window = Mock()

        with patch.object(main_module, "build_arg_parser", return_value=parser):
            with patch.object(main_module, "QApplication", return_value=app):
                with patch.object(main_module, "build_main_window", return_value=window):
                    with patch("astroview.main.QTimer.singleShot") as single_shot_mock:
                        with patch.object(main_module, "_resource_path", return_value=Path(".")):
                            result = main_module.main()

        self.assertEqual(result, 0)
        window.initialize.assert_called_once_with(apply_startup_request=False)
        window.show.assert_called_once_with()
        single_shot_mock.assert_called_once_with(0, window.schedule_startup_request)
        app.exec.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
