import multiprocessing


def _run() -> int:
    """Run the PyInstaller entry point with spawn-child compatibility."""

    multiprocessing.freeze_support()
    from astroview.main import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
