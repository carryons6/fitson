from pathlib import Path
import sys
import sysconfig

import PyInstaller.building.build_main as build_main
import numpy
import PySide6
import shiboken6
from PyInstaller.utils.win32 import versioninfo


spec_dir = Path(SPECPATH).resolve()
package_dir = spec_dir
workspace_dir = package_dir.parent
env_dir = Path(sys.executable).resolve().parent
site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
python3_dll = env_dir / "python3.dll"
python_dlls_dir = env_dir / "DLLs"
pyside_package_dir = Path(PySide6.__file__).resolve().parent
shiboken_package_dir = Path(shiboken6.__file__).resolve().parent
numpy_libs_dir = Path(numpy.__file__).resolve().parent.parent / "numpy.libs"

# The active environment may contain broken entry points that crash hook
# auto-discovery. We bypass the entry-point scan and provide the needed hook
# directories explicitly.
build_main.discover_hook_directories = lambda: []

# In some environments, PyInstaller's isolated package import used during
# find_binary_dependencies() crashes when importing astroview.core. We bypass
# that late scan and add the needed runtime DLLs explicitly below.
build_main.find_binary_dependencies = lambda *args, **kwargs: []

hookspath = [str(spec_dir / "hooks")]
numpy_hook_dir = site_packages / "numpy" / "_pyinstaller"
if numpy_hook_dir.is_dir():
    hookspath.append(str(numpy_hook_dir))

qt_bin = env_dir / "Library" / "bin"
qt_shiboken_dir = env_dir / "Library" / "shiboken6"
blas_shim_dlls = [
    "libcblas.dll",
    "libblas.dll",
    "liblapack.dll",
    "liblapacke.dll",
]
openblas_dll_patterns = [
    "openblas*.dll",
    "libopenblas*.dll",
]
mkl_runtime_dlls = [
    "mkl_rt.2.dll",
    "mkl_core.2.dll",
    "mkl_intel_thread.2.dll",
    "mkl_def.2.dll",
    "mkl_avx2.2.dll",
    "mkl_vml_avx2.2.dll",
    "mkl_vml_def.2.dll",
    "mkl_vml_cmpt.2.dll",
]

binaries = []
if python3_dll.is_file():
    binaries.append((str(python3_dll), "."))


def _append_binary_if_exists(source_dir: Path, dll_name: str, dest: str = ".") -> None:
    dll_path = source_dir / dll_name
    if dll_path.is_file():
        binaries.append((str(dll_path), dest))


def _append_binary_glob_if_exists(source_dir: Path, pattern: str, dest: str = ".") -> None:
    for dll_path in source_dir.glob(pattern):
        if dll_path.is_file():
            binaries.append((str(dll_path), dest))


def _binary_contains_ascii_tokens(dll_path: Path, tokens: tuple[bytes, ...]) -> bool:
    if not dll_path.is_file():
        return False
    content = dll_path.read_bytes()
    return any(token in content for token in tokens)


def _collect_blas_runtime_binaries(source_dir: Path) -> str:
    # Conda BLAS shims forward to the real backend via exported ASCII names, so
    # PyInstaller cannot discover the backend DLLs automatically.
    for dll_name in blas_shim_dlls:
        _append_binary_if_exists(source_dir, dll_name)

    shim_paths = [source_dir / dll_name for dll_name in blas_shim_dlls]
    if any(
        _binary_contains_ascii_tokens(shim_path, (b"openblas.dll", b"openblas"))
        for shim_path in shim_paths
    ):
        for pattern in openblas_dll_patterns:
            _append_binary_glob_if_exists(source_dir, pattern)
        return "openblas"

    if any(
        _binary_contains_ascii_tokens(shim_path, (b"mkl_rt", b"mkl_core", b"mkl_vml"))
        for shim_path in shim_paths
    ):
        for dll_name in mkl_runtime_dlls:
            _append_binary_if_exists(source_dir, dll_name)
        return "mkl"

    return "unknown"


_append_binary_if_exists(python_dlls_dir, "_ssl.pyd")

# Conda BLAS uses forwarding shims (libcblas/libblas/liblapack); collect only
# the runtime backend actually referenced by those shims.
blas_backend = _collect_blas_runtime_binaries(qt_bin)


# PySide6 / Shiboken runtime DLLs. Prefer package-local DLLs because the exact
# filenames vary across conda/PyPI builds (for example abi3 vs cp311 suffixes).
for dll_name in [
    "Qt6Core.dll",
    "Qt6Gui.dll",
    "Qt6Widgets.dll",
]:
    _append_binary_if_exists(pyside_package_dir, dll_name)
    _append_binary_if_exists(qt_bin, dll_name)

for pattern in [
    "pyside6*.dll",
]:
    _append_binary_glob_if_exists(pyside_package_dir, pattern)
    _append_binary_glob_if_exists(qt_bin, pattern)

for dll_name in [
    "concrt140.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_codecvt_ids.dll",
    "vccorlib140.dll",
    "vcomp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
]:
    _append_binary_if_exists(shiboken_package_dir, dll_name)
    _append_binary_if_exists(qt_shiboken_dir, dll_name)
    _append_binary_if_exists(qt_bin, dll_name)

for pattern in [
    "shiboken6*.dll",
]:
    _append_binary_glob_if_exists(shiboken_package_dir, pattern)
    _append_binary_glob_if_exists(qt_shiboken_dir, pattern)
    _append_binary_glob_if_exists(qt_bin, pattern)

# ICU and Qt6 transitive dependencies usually live under Library/bin.
for dll_name in [
    "icudt78.dll",
    "icuin78.dll",
    "icuuc78.dll",
    "freetype.dll",
    "libpng16.dll",
    "pcre2-16.dll",
    "double-conversion.dll",
    "zstd.dll",
    "libssl-3-x64.dll",
    "libcrypto-3-x64.dll",
    "libgomp-1.dll",
    "libquadmath-0.dll",
    "libgcc_s_seh-1.dll",
]:
    _append_binary_if_exists(qt_bin, dll_name)

# Conda/PyPI numpy wheels often depend on hashed OpenBLAS runtime DLLs under
# numpy.libs; collect them explicitly because binary dependency discovery is
# bypassed above.
if numpy_libs_dir.is_dir():
    for dll_path in numpy_libs_dir.glob("*.dll"):
        binaries.append((str(dll_path), "."))

seen_binaries = set()
unique_binaries = []
for src, dest in binaries:
    key = (src, dest)
    if key in seen_binaries:
        continue
    seen_binaries.add(key)
    unique_binaries.append((src, dest))
binaries = unique_binaries


datas = []
runtime_icon = spec_dir / "resources" / "icons" / "main_icon.png"
if runtime_icon.is_file():
    datas.append((str(runtime_icon), "astroview/resources/icons"))
version_file = spec_dir / "VERSION"
if version_file.is_file():
    datas.append((str(version_file), "astroview"))
app_version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "0.0.0"


def _parse_windows_version(version_text: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version_text.split(".") if part.strip()]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def _build_windows_version_info(version_text: str) -> versioninfo.VSVersionInfo:
    version_tuple = _parse_windows_version(version_text)
    return versioninfo.VSVersionInfo(
        ffi=versioninfo.FixedFileInfo(
            filevers=version_tuple,
            prodvers=version_tuple,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            versioninfo.StringFileInfo(
                [
                    versioninfo.StringTable(
                        "040904B0",
                        [
                            versioninfo.StringStruct("CompanyName", "Fitson"),
                            versioninfo.StringStruct("FileDescription", "AstroView"),
                            versioninfo.StringStruct("FileVersion", version_text),
                            versioninfo.StringStruct("InternalName", "AstroView.exe"),
                            versioninfo.StringStruct("OriginalFilename", "AstroView.exe"),
                            versioninfo.StringStruct("ProductName", "AstroView"),
                            versioninfo.StringStruct("ProductVersion", version_text),
                        ],
                    )
                ]
            ),
            versioninfo.VarFileInfo([versioninfo.VarStruct("Translation", [1033, 1200])]),
        ],
    )


windows_version_info = _build_windows_version_info(app_version)

hiddenimports = [
    "sep",
    "numpy._core._multiarray_tests",
    "secrets",
    "hmac",
    "hashlib",
]


a = Analysis(
    [str(package_dir / "astroview_bootstrap.py")],
    pathex=[str(workspace_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=hookspath,
    hooksconfig={},
    runtime_hooks=[str(spec_dir / "rthooks" / "pyi_rth_dll_search_paths.py")],
    excludes=[
        "PyQt6",
        "IPython",
        "PIL",
        "aiohttp",
        "bottleneck",
        "botocore",
        "dask",
        "fsspec",
        "h5py",
        "jedi",
        "matplotlib",
        "openpyxl",
        "pandas",
        "prompt_toolkit",
        "pyarrow",
        "pygments",
        "psutil",
        "pygame",
        "scipy",
        "tkinter",
        "_tkinter",
        "tornado",
        "zmq",
        "sqlite3",
        "_sqlite3",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "test",
        "unittest",
        "xmlrpc",
        "doctest",
        "lib2to3",
    ],
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------------------
# Strip oversized / unnecessary files from the bundle
# ---------------------------------------------------------------------------
import re

# Keep only the MKL DLLs that numpy actually loads at runtime; strip the rest.
_mkl_keep = {
    "mkl_rt.2.dll", "mkl_core.2.dll", "mkl_intel_thread.2.dll",
    "mkl_def.2.dll", "mkl_avx2.2.dll",
    "mkl_vml_avx2.2.dll", "mkl_vml_def.2.dll", "mkl_vml_cmpt.2.dll",
}
_strip_patterns = [
    re.compile(r"^mkl_", re.I),  # caught first, but _should_strip checks _mkl_keep
    re.compile(r"^icudt\.dll$", re.I),
    # Duplicate unversioned ICU DLLs (keep only versioned icuXX78.dll variants)
    re.compile(r"^icu(in|uc)\.dll$", re.I),
    # ICU DLLs not needed by PySide6
    re.compile(r"^icu(io|test|tu)", re.I),
    # Tcl/Tk because tkinter is excluded
    re.compile(r"^(tcl|tk)\d", re.I),
    # Software OpenGL fallback — not needed for desktop app (saves ~20 MB)
    re.compile(r"^opengl32sw\.dll$", re.I),
    # SQLite — module excluded above (saves ~3 MB)
    re.compile(r"^sqlite3\.dll$", re.I),
    # Qt6Network — app has no network I/O (saves ~1.4 MB)
    re.compile(r"^Qt6Network\.dll$", re.I),
]

_strip_exact_binaries = {
    "qcertonlybackend.dll",
    "qdirect2d.dll",
    "qgif.dll",
    "qicns.dll",
    "qico.dll",
    "qjpeg.dll",
    "qminimal.dll",
    "qmodernwindowsstyle.dll",
    "qnetworklistmanager.dll",
    "qoffscreen.dll",
    "qopensslbackend.dll",
    "qpdf.dll",
    "qschannelbackend.dll",
    "qsvg.dll",
    "qsvgicon.dll",
    "qtga.dll",
    "qtiff.dll",
    "qtvirtualkeyboardplugin.dll",
    "qtuiotouchplugin.dll",
    "qwbmp.dll",
    "qwebp.dll",
    # PySide6 network binding — unused
    "QtNetwork.pyd",
}

_strip_path_fragments = (
    "pyside6/translations/",
    "astropy/extern/jquery/",
    "astropy/io/votable/",
    "astropy/cosmology/data/",
    "astropy/samp/",
    "astropy/table/",
    "astropy/timeseries/",
    "astropy/wcs/include/",
    "astropy/io/votable/validator/data/",
    "astropy/wcs/src/",
    "astropy/io/ascii/src/",
    "astropy/convolution/src/",
    "astropy/stats/src/",
    "astropy/utils/xml/src/",
)

_strip_exact_data = {
    "record",
    "installer",
    "requested",
}


def _should_strip(name):
    basename = Path(name).name.lower()
    if basename in _mkl_keep:
        return False
    if basename in _strip_exact_binaries:
        return True
    for pat in _strip_patterns:
        if pat.search(basename):
            return True
    return False


def _should_strip_data(path):
    parts = [
        part.replace("\\", "/").lower()
        for part in path
        if isinstance(part, str)
    ] if isinstance(path, tuple) else [str(path).replace("\\", "/").lower()]

    for normalized in parts:
        basename = Path(normalized).name
        if basename in _strip_exact_data and ".dist-info/" in normalized:
            return True
        if normalized.startswith("astropy/") and normalized.endswith((".pyx", ".c", ".h")):
            return True
        if any(fragment in normalized for fragment in _strip_path_fragments):
            return True
    return False


a.binaries = [b for b in a.binaries if not _should_strip(b[0])]

# Remove astropy test directories from collected data
a.datas = [
    d for d in a.datas
    if "/tests/" not in d[0].replace("\\", "/")
    and "/test/" not in d[0].replace("\\", "/")
    and not _should_strip_data(d)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AstroView",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=[str(spec_dir / "resources" / "icons" / "main_icon.ico")],
    version=windows_version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AstroView",
)
