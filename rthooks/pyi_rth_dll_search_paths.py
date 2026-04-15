from __future__ import annotations

import os
from pathlib import Path
import sys

_DLL_DIR_HANDLES = []

if sys.platform.startswith("win") and hasattr(os, "add_dll_directory"):
    root = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    for candidate in (root, root / "numpy.libs", root / "numpy" / "_core", root / "numpy" / "linalg"):
        if candidate.is_dir():
            try:
                _DLL_DIR_HANDLES.append(os.add_dll_directory(str(candidate)))
            except OSError:
                pass
