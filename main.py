from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .app import MainWindow
from .app.i18n import install_translator
from .app.theme import apply_theme, load_saved_theme
from .core import OpenFileRequest
from .diagnostics import install_exception_hooks, log_shutdown, log_startup


def _resource_path() -> Path:
    """Return the resources directory, works both in dev and PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "astroview" / "resources"
    return Path(__file__).resolve().parent / "resources"


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for the application entry point."""

    parser = argparse.ArgumentParser(description="AstroView application entry point.")
    parser.add_argument("path", nargs="?", help="Optional FITS file path.")
    parser.add_argument("--hdu", type=int, default=None, help="Optional HDU index.")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def _write_smoke_report(message: str) -> None:
    """Best-effort report for the windowed frozen executable's build check."""

    report_path = os.environ.get("ASTROVIEW_SMOKE_REPORT")
    if not report_path:
        return
    try:
        Path(report_path).write_text(message.rstrip() + "\n", encoding="utf-8")
    except OSError:
        # The process exit code remains authoritative when the report location
        # itself is not writable.
        pass


def run_smoke_test() -> int:
    """Exercise frozen GUI and scientific dependencies without opening a window."""

    try:
        import numpy as np
        import sep
        from astropy.io import fits

        app = QApplication.instance() or QApplication([APP_NAME, "--smoke-test"])
        apply_theme(app, "light")

        icon_path = _resource_path() / "icons" / "main_icon.png"
        if not icon_path.is_file():
            raise FileNotFoundError(f"Bundled application icon is missing: {icon_path}")
        app.setWindowIcon(QIcon(str(icon_path)))

        sample = np.zeros((16, 16), dtype=np.float32)
        fits.PrimaryHDU(data=sample).verify("exception")
        sep.extract(sample, 1.0)
        app.processEvents()
    except Exception:
        _write_smoke_report("FAILED\n" + traceback.format_exc())
        return 1

    _write_smoke_report(f"OK {APP_NAME} {__version__}")
    return 0


def build_startup_request(args: argparse.Namespace) -> OpenFileRequest | None:
    """Convert parsed CLI arguments into a structured startup request."""

    if not args.path:
        return None
    return OpenFileRequest(path=args.path, hdu_index=args.hdu)


def build_main_window(args: argparse.Namespace) -> MainWindow:
    """Create the top-level window with startup request metadata."""

    request = build_startup_request(args)
    if request is None:
        return MainWindow()
    return MainWindow(initial_path=request.path, initial_hdu=request.hdu_index)


def main() -> int:
    """Application entry point.

    - Parse CLI arguments.
    - Create QApplication and MainWindow.
    - Call initialize(), show the window, and enter the event loop.
    """

    parser = build_arg_parser()
    args = parser.parse_args()

    if getattr(args, "smoke_test", False):
        return run_smoke_test()

    log_path = install_exception_hooks(APP_NAME)
    log_startup(__name__, __version__, sys.argv)

    app = QApplication(sys.argv)
    install_translator(app)
    apply_theme(app, load_saved_theme())

    icon_path = _resource_path() / "icons" / "main_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = build_main_window(args)
    logging.getLogger(__name__).info("Runtime log file: %s", log_path)
    window.initialize(apply_startup_request=False)
    window.show()
    QTimer.singleShot(0, window.schedule_startup_request)
    exit_code = app.exec()
    log_shutdown(__name__, exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
