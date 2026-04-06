from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import traceback
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


LOGGER_NAME = "astroview"


def app_data_directory(app_name: str, *, platform: str | None = None) -> Path:
    """Return a per-user writable application data directory."""

    normalized_platform = platform or sys.platform
    home = Path.home()

    if normalized_platform.startswith("win"):
        root = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return root / app_name

    if normalized_platform == "darwin":
        return home / "Library" / "Application Support" / app_name

    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / app_name
    return home / ".local" / "state" / app_name


def log_file_path(app_name: str) -> Path:
    """Return the rotating log-file path used by the application."""

    return app_data_directory(app_name) / "logs" / f"{LOGGER_NAME}.log"


def configure_logging(app_name: str) -> Path:
    """Configure file-backed runtime logging once and return the log path."""

    log_path = log_file_path(app_name)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if getattr(handler, "_astroview_log_handler", False):
            return log_path

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    file_handler._astroview_log_handler = True  # type: ignore[attr-defined]

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    logging.captureWarnings(True)
    return log_path


def _format_exception_message(exc_value: BaseException, log_path: Path) -> str:
    return (
        "AstroView encountered an unexpected error.\n\n"
        f"{exc_value}\n\n"
        f"Details were written to:\n{log_path}"
    )


def _show_fatal_error_dialog(message: str) -> None:
    app = QApplication.instance()
    if app is None:
        return
    active_window = app.activeWindow()
    parent = active_window if isinstance(active_window, QWidget) else None
    QMessageBox.critical(parent, "AstroView Error", message)


def _log_unhandled_exception(
    log_path: Path,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    _show_fatal_error_dialog(_format_exception_message(exc_value, log_path))


def install_exception_hooks(app_name: str) -> Path:
    """Install unhandled-exception hooks that log to the runtime log file."""

    log_path = configure_logging(app_name)

    def _sys_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        _log_unhandled_exception(log_path, exc_type, exc_value, exc_traceback)

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        _log_unhandled_exception(log_path, args.exc_type, args.exc_value, args.exc_traceback)

    def _unraisable_hook(args: object) -> None:
        exc_type = type(getattr(args, "exc_value", RuntimeError("Unraisable exception")))
        exc_value = getattr(args, "exc_value", RuntimeError("Unraisable exception"))
        exc_traceback = getattr(args, "exc_traceback", None)
        logging.getLogger(LOGGER_NAME).error(
            "Unraisable exception in %s",
            getattr(args, "object", "<unknown>"),
        )
        _log_unhandled_exception(log_path, exc_type, exc_value, exc_traceback)

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable_hook
    return log_path


def log_startup(logger_name: str, version: str, argv: list[str]) -> None:
    """Record a concise startup event for diagnostics."""

    logging.getLogger(logger_name).info("Starting AstroView %s with argv=%s", version, argv)


def log_shutdown(logger_name: str, exit_code: int) -> None:
    """Record application shutdown for diagnostics."""

    logging.getLogger(logger_name).info("AstroView exited with code %s", exit_code)


def log_current_exception(logger_name: str, context: str) -> str:
    """Log the current exception context and return its traceback string."""

    payload = f"{context}\n{traceback.format_exc()}"
    logging.getLogger(logger_name).error("%s", payload.rstrip())
    return payload
