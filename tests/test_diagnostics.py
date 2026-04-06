from __future__ import annotations

import logging
import tempfile
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.diagnostics import app_data_directory, configure_logging, log_current_exception


class TestDiagnostics(unittest.TestCase):
    def test_app_data_directory_uses_platform_conventions(self) -> None:
        with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"}, clear=False):
            self.assertEqual(
                app_data_directory("AstroView", platform="win32"),
                Path(r"C:\Users\Test\AppData\Local") / "AstroView",
            )

        self.assertEqual(
            app_data_directory("AstroView", platform="darwin"),
            Path.home() / "Library" / "Application Support" / "AstroView",
        )

    def test_configure_logging_creates_log_file_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "AstroView" / "logs" / "astroview.log"
            with patch("astroview.diagnostics.log_file_path", return_value=log_path):
                root_logger = logging.getLogger()
                original_handlers = list(root_logger.handlers)
                try:
                    configured_path = configure_logging("AstroView")
                    self.assertEqual(configured_path, log_path)
                    self.assertTrue(
                        any(getattr(handler, "_astroview_log_handler", False) for handler in root_logger.handlers)
                    )
                finally:
                    for handler in list(root_logger.handlers):
                        if getattr(handler, "_astroview_log_handler", False):
                            root_logger.removeHandler(handler)
                            handler.close()
                    for handler in original_handlers:
                        if handler not in root_logger.handlers:
                            root_logger.addHandler(handler)

    def test_log_current_exception_returns_traceback_text(self) -> None:
        with self.assertLogs("astroview.tests", level="ERROR") as captured:
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                payload = log_current_exception("astroview.tests", "While testing")

        self.assertIn("RuntimeError: boom", payload)
        self.assertIn("While testing", payload)
        self.assertTrue(any("While testing" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()
