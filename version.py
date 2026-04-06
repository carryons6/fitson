from __future__ import annotations

from pathlib import Path


def _version_file() -> Path:
    """Return the repository version file."""

    return Path(__file__).resolve().parent / "VERSION"


def read_version() -> str:
    """Read the application version from the repository version file."""

    return _version_file().read_text(encoding="utf-8").strip()


__version__ = read_version()
