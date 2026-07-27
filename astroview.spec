from pathlib import Path
import re
import shutil
import sys
import sysconfig

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


def _require_binary(source_dirs: list[Path], dll_name: str, dest: str = ".") -> list[Path]:
    """Collect every matching critical binary and fail the build if absent."""

    matches = []
    for source_dir in source_dirs:
        dll_path = source_dir / dll_name
        if dll_path.is_file():
            matches.append(dll_path)
            binaries.append((str(dll_path), dest))
    if not matches:
        searched = ", ".join(str(source_dir / dll_name) for source_dir in source_dirs)
        raise FileNotFoundError(f"Required runtime binary {dll_name!r} was not found; searched: {searched}")
    return matches


def _require_binary_glob(source_dirs: list[Path], pattern: str, dest: str = ".") -> list[Path]:
    """Collect critical binaries matching a platform-dependent filename."""

    matches = []
    for source_dir in source_dirs:
        for dll_path in source_dir.glob(pattern):
            if dll_path.is_file():
                matches.append(dll_path)
                binaries.append((str(dll_path), dest))
    if not matches:
        searched = ", ".join(str(source_dir / pattern) for source_dir in source_dirs)
        raise FileNotFoundError(f"Required runtime binary pattern {pattern!r} had no matches; searched: {searched}")
    return matches


def _binary_contains_ascii_tokens(dll_path: Path, tokens: tuple[bytes, ...]) -> bool:
    if not dll_path.is_file():
        return False
    content = dll_path.read_bytes()
    return any(token in content for token in tokens)


def _collect_blas_runtime_binaries(source_dir: Path) -> str:
    # Conda BLAS shims forward to the real backend via exported ASCII names, so
    # PyInstaller cannot discover the backend DLLs automatically.
    shim_paths = [source_dir / dll_name for dll_name in blas_shim_dlls]
    existing_shims = [shim_path for shim_path in shim_paths if shim_path.is_file()]
    for shim_path in existing_shims:
        binaries.append((str(shim_path), "."))
    if not existing_shims:
        return "none"

    if any(
        _binary_contains_ascii_tokens(shim_path, (b"openblas.dll", b"openblas"))
        for shim_path in existing_shims
    ):
        backend_matches = []
        for pattern in openblas_dll_patterns:
            for dll_path in source_dir.glob(pattern):
                if dll_path.is_file():
                    backend_matches.append(dll_path)
                    binaries.append((str(dll_path), "."))
        if not backend_matches:
            raise FileNotFoundError("Conda BLAS shims require OpenBLAS, but no OpenBLAS runtime DLL was found")
        return "openblas"

    if any(
        _binary_contains_ascii_tokens(shim_path, (b"mkl_rt", b"mkl_core", b"mkl_vml"))
        for shim_path in existing_shims
    ):
        _require_binary([source_dir], "mkl_rt.2.dll")
        _require_binary([source_dir], "mkl_core.2.dll")
        for dll_name in mkl_runtime_dlls:
            _append_binary_if_exists(source_dir, dll_name)
        return "mkl"

    raise RuntimeError(
        "Conda BLAS forwarding shims were found, but their runtime backend could not be identified"
    )


_require_binary([python_dlls_dir], "_ssl.pyd")

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
    _require_binary([pyside_package_dir, qt_bin], dll_name)

_require_binary_glob([pyside_package_dir, qt_bin], "pyside6*.dll")

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

_require_binary_glob(
    [shiboken_package_dir, qt_shiboken_dir, qt_bin],
    "shiboken6*.dll",
)


def _collect_conda_icu_binaries(source_dir: Path) -> str | None:
    """Collect a complete versioned ICU trio without assuming an ICU release."""

    # PyPI PySide wheels bundle a self-contained Qt.  Conda Qt places Qt6Core
    # and its versioned ICU dependencies in Library/bin.
    if not (source_dir / "Qt6Core.dll").is_file():
        return None

    versions: dict[str, dict[str, Path]] = {}
    pattern = re.compile(r"^icu(dt|in|uc)(\d+)\.dll$", re.IGNORECASE)
    for dll_path in source_dir.glob("icu*.dll"):
        match = pattern.match(dll_path.name)
        if match:
            component, version = match.groups()
            versions.setdefault(version, {})[component.lower()] = dll_path

    complete_versions = [
        version
        for version, components in versions.items()
        if {"dt", "in", "uc"}.issubset(components)
    ]
    if not complete_versions:
        raise FileNotFoundError(
            f"Conda Qt was found in {source_dir}, but no complete versioned ICU runtime trio was found"
        )

    selected_version = max(complete_versions, key=int)
    for component in ("dt", "in", "uc"):
        binaries.append((str(versions[selected_version][component]), "."))
    return selected_version


# ICU and other Qt6 transitive dependencies usually live under Library/bin.
_collect_conda_icu_binaries(qt_bin)
if (qt_bin / "Qt6Core.dll").is_file():
    for dll_name in [
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
        "yaml.dll",
    ]:
        _require_binary([qt_bin], dll_name)

# Conda/PyPI numpy wheels often depend on hashed OpenBLAS runtime DLLs under
# numpy.libs; collect them explicitly in addition to PyInstaller's dependency
# analysis, then fail if neither a Conda nor wheel BLAS runtime was found.
numpy_runtime_dlls = []
if numpy_libs_dir.is_dir():
    for dll_path in numpy_libs_dir.glob("*.dll"):
        numpy_runtime_dlls.append(dll_path)
        binaries.append((str(dll_path), "."))
if blas_backend == "none" and not numpy_runtime_dlls:
    raise FileNotFoundError(
        "No external NumPy BLAS runtime was found in the Conda environment or numpy.libs"
    )

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
if not runtime_icon.is_file():
    raise FileNotFoundError(f"Required runtime icon is missing: {runtime_icon}")
datas.append((str(runtime_icon), "astroview/resources/icons"))
version_file = spec_dir / "VERSION"
if not version_file.is_file():
    raise FileNotFoundError(f"Required VERSION file is missing: {version_file}")
datas.append((str(version_file), "astroview"))
app_version = version_file.read_text(encoding="utf-8").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+", app_version):
    raise ValueError(f"VERSION must be an x.y.z numeric version, got {app_version!r}")


def _prepare_source_package_alias() -> Path:
    """Expose this checkout as an `astroview` package for PyInstaller analysis."""

    alias_parent = spec_dir / "build" / "package_alias"
    alias_package = alias_parent / "astroview"
    if alias_package.exists():
        shutil.rmtree(alias_package)
    alias_package.mkdir(parents=True, exist_ok=True)

    for filename in [
        "__init__.py",
        "__main__.py",
        "main.py",
        "metadata.py",
        "diagnostics.py",
        "version.py",
        "VERSION",
    ]:
        shutil.copy2(package_dir / filename, alias_package / filename)

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    for dirname in ["app", "core"]:
        shutil.copytree(package_dir / dirname, alias_package / dirname, ignore=ignore)

    return alias_parent


package_alias_parent = _prepare_source_package_alias()


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
    "astroview.main",
    "astropy.time",
    "sep",
    "numpy._core._multiarray_tests",
    "secrets",
    "hmac",
    "hashlib",
]


a = Analysis(
    [str(package_dir / "astroview_bootstrap.py")],
    pathex=[str(package_alias_parent), str(package_dir), str(workspace_dir)],
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

# Keep only the MKL DLLs that numpy actually loads at runtime; strip the rest.
_mkl_keep = {
    "mkl_rt.2.dll", "mkl_core.2.dll", "mkl_intel_thread.2.dll",
    "mkl_def.2.dll", "mkl_avx2.2.dll",
    "mkl_vml_avx2.2.dll", "mkl_vml_def.2.dll", "mkl_vml_cmpt.2.dll",
}
_strip_patterns = [
    re.compile(r"^mkl_", re.I),  # caught first, but _should_strip checks _mkl_keep
    re.compile(r"^icudt\.dll$", re.I),
    # Duplicate unversioned ICU DLLs (the dynamically selected versioned trio is kept)
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
