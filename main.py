from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .app import MainWindow
from .core import OpenFileRequest


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
    return parser


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

    app = QApplication(sys.argv)

    icon_path = _resource_path() / "icons" / "main_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = build_main_window(args)
    window.initialize(apply_startup_request=False)
    window.show()
    QTimer.singleShot(0, window.schedule_startup_request)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
