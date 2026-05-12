from __future__ import annotations

import sys
from pathlib import Path


package_dir = Path(__file__).resolve().parent

if __package__ in (None, ""):
    # When this source tree is checked out to a directory that is not literally
    # named "astroview", importing this launcher as top-level `astroview` would
    # otherwise shadow the package and make `astroview.main` unresolvable.
    __package__ = "astroview"
    __path__ = [str(package_dir)]  # type: ignore[var-annotated]
    package_parent = package_dir.parent
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))

from astroview.version import __version__

APP_NAME = "AstroView"
APP_REPOSITORY = "Suiren0816/fitson"
APP_RELEASES_URL = f"https://github.com/{APP_REPOSITORY}/releases"
APP_RELEASES_API_URL = f"https://api.github.com/repos/{APP_REPOSITORY}/releases/latest"
APP_TAGS_API_URL = f"https://api.github.com/repos/{APP_REPOSITORY}/tags?per_page=1"
from astroview.main import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
