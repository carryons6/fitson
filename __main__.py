import multiprocessing


def _run() -> int:
    """Run the package entry point with Windows spawn/frozen compatibility."""

    multiprocessing.freeze_support()
    from .main import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
