import multiprocessing
import os
from pathlib import Path


def _write_smoke_stage(message: str) -> None:
    """Record frozen-startup progress when the release smoke test requests it."""

    report_path = os.environ.get("ASTROVIEW_SMOKE_REPORT")
    if not report_path:
        return
    try:
        Path(report_path).write_text(message.rstrip() + "\n", encoding="utf-8")
    except OSError:
        pass


def _run() -> int:
    """Run the PyInstaller entry point with spawn-child compatibility."""

    multiprocessing.freeze_support()
    _write_smoke_stage("RUNNING import astroview.main")
    from astroview.main import main

    _write_smoke_stage("RUNNING dispatch astroview.main")
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
