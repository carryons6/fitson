from __future__ import annotations

import argparse
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview import main as main_module


class TestMainEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_package_main_module_does_not_run_app_on_import(self) -> None:
        sys.modules.pop("astroview.__main__", None)

        with patch("astroview.main.main") as main_mock:
            importlib.import_module("astroview.__main__")

        main_mock.assert_not_called()

    def test_main_defers_startup_file_open_until_after_window_show(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = argparse.Namespace(path="demo.fits", hdu=None)
        app = Mock()
        app.exec.return_value = 0
        window = Mock()

        with patch.object(main_module, "build_arg_parser", return_value=parser):
            with patch.object(main_module, "QApplication", return_value=app):
                with patch.object(main_module, "build_main_window", return_value=window):
                    with patch.object(main_module, "install_translator") as install_translator_mock:
                        with patch("astroview.main.QTimer.singleShot") as single_shot_mock:
                            with patch.object(main_module, "_resource_path", return_value=Path(".")):
                                with patch.object(main_module, "install_exception_hooks", return_value=Path("astroview.log")):
                                    with patch.object(main_module, "log_startup"):
                                        with patch.object(main_module, "log_shutdown"):
                                            with patch.object(main_module, "apply_theme"):
                                                with patch.object(main_module, "load_saved_theme", return_value="light"):
                                                    result = main_module.main()

        self.assertEqual(result, 0)
        install_translator_mock.assert_called_once_with(app)
        window.initialize.assert_called_once_with(apply_startup_request=False)
        window.show.assert_called_once_with()
        single_shot_mock.assert_called_once_with(0, window.schedule_startup_request)
        app.exec.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
