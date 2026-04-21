import multiprocessing

from .main import main


def _run() -> int:
    """Run the package entry point with Windows spawn/frozen compatibility."""

    multiprocessing.freeze_support()
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
