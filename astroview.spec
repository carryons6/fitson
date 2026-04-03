from pathlib import Path

import PyInstaller.building.build_main as build_main


spec_dir = Path(SPECPATH).resolve()
package_dir = spec_dir
workspace_dir = package_dir.parent
site_packages = Path(r"D:\Miniforge\envs\astro\Lib\site-packages")
python3_dll = Path(r"D:\Miniforge\envs\astro\python3.dll")
pyside_package_dir = site_packages / "PySide6"
shiboken_package_dir = site_packages / "shiboken6"
numpy_libs_dir = site_packages / "numpy.libs"

# The astro environment contains a broken pygame PyInstaller entry point that
# crashes hook auto-discovery. We bypass the entry-point scan and provide the
# needed hook directories explicitly.
build_main.discover_hook_directories = lambda: []

# In the same environment, PyInstaller's isolated package import used during
# find_binary_dependencies() crashes when importing astroview.core. We bypass
# that late scan and add the needed runtime DLLs explicitly below.
build_main.find_binary_dependencies = lambda *args, **kwargs: []

hookspath = [str(spec_dir / "hooks")]
numpy_hook_dir = site_packages / "numpy" / "_pyinstaller"
if numpy_hook_dir.is_dir():
    hookspath.append(str(numpy_hook_dir))

qt_bin = Path(r"D:\Miniforge\envs\astro\Library\bin")
icu_bin = qt_bin  # ICU DLLs are in the same directory

binaries = []
if python3_dll.is_file():
    binaries.append((str(python3_dll), '.'))

def _append_binary_if_exists(source_dir: Path, dll_name: str, dest: str = '.') -> None:
    dll_path = source_dir / dll_name
    if dll_path.is_file():
        binaries.append((str(dll_path), dest))


# PySide6 / Shiboken runtime DLLs. Prefer package-local DLLs because the exact
# filenames vary across conda/PyPI builds (for example abi3 vs cp311 suffixes).
for dll_name in [
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll',
    'pyside6.abi3.dll', 'pyside6qml.abi3.dll',
]:
    _append_binary_if_exists(pyside_package_dir, dll_name)
    _append_binary_if_exists(qt_bin, dll_name)

for dll_name in [
    'shiboken6.abi3.dll',
    'concrt140.dll',
    'msvcp140.dll',
    'msvcp140_1.dll',
    'msvcp140_2.dll',
    'msvcp140_codecvt_ids.dll',
    'vccorlib140.dll',
    'vcomp140.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
]:
    _append_binary_if_exists(shiboken_package_dir, dll_name)
    _append_binary_if_exists(qt_bin, dll_name)

# ICU and Qt6 transitive dependencies usually live under Library/bin.
for dll_name in [
    'icudt.dll', 'icudt78.dll',
    'icuin.dll', 'icuin78.dll',
    'icuuc.dll', 'icuuc78.dll',
    'freetype.dll', 'libpng16.dll', 'pcre2-16.dll',
    'double-conversion.dll', 'zstd.dll',
    'libgomp-1.dll', 'libquadmath-0.dll', 'libgcc_s_seh-1.dll',
]:
    _append_binary_if_exists(qt_bin, dll_name)

# Conda/PyPI numpy wheels often depend on hashed OpenBLAS runtime DLLs under
# numpy.libs; collect them explicitly because binary dependency discovery is
# bypassed above.
if numpy_libs_dir.is_dir():
    for dll_path in numpy_libs_dir.glob("*.dll"):
        binaries.append((str(dll_path), '.'))

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

hiddenimports = [
    "sep",
    "numpy.core._multiarray_tests",
]


a = Analysis(
    [str(package_dir / "astroview_bootstrap.py")],
    pathex=[str(workspace_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=hookspath,
    hooksconfig={},
    runtime_hooks=[],
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

# MKL DLLs (~420 MB) are not needed when numpy uses OpenBLAS.
# Even if MKL is still the BLAS backend at build time, we strip the DLLs that
# are never called at runtime (avx512/avx2/mc3/tbb variants, scalapack, etc.).
# Keep only mkl_rt and mkl_core + one threading layer if MKL is still present.
_mkl_keep = {'mkl_rt.2.dll', 'mkl_core.2.dll', 'mkl_intel_thread.2.dll'}
_strip_patterns = [
    # MKL variants we never need
    re.compile(r'mkl_(avx|mc3|def|tbb|sequential|vml|scalapack|blacs|pari).*\.dll$', re.I),
    # ICU DLLs not needed by PySide6 (keep icudt, icuin, icuuc + versioned variants)
    re.compile(r'^icu(io|test|tu)', re.I),
    # Tcl/Tk because tkinter is excluded
    re.compile(r'^(tcl|tk)\d', re.I),
]

_strip_exact_binaries = {
    'qcertonlybackend.dll',
    'qdirect2d.dll',
    'qgif.dll',
    'qicns.dll',
    'qico.dll',
    'qjpeg.dll',
    'qminimal.dll',
    'qmodernwindowsstyle.dll',
    'qnetworklistmanager.dll',
    'qoffscreen.dll',
    'qopensslbackend.dll',
    'qschannelbackend.dll',
    'qsvg.dll',
    'qsvgicon.dll',
    'qtga.dll',
    'qtiff.dll',
    'qtuiotouchplugin.dll',
    'qwbmp.dll',
    'qwebp.dll',
}

_strip_path_fragments = (
    'pyside6/translations/',
    'astropy/io/votable/validator/data/',
    'astropy/wcs/src/',
)

_strip_exact_data = {
    'record',
}


def _should_strip(name):
    basename = Path(name).name.lower()
    if basename in _strip_exact_binaries:
        return True
    for pat in _strip_patterns:
        if pat.search(basename):
            return True
    return False


def _should_strip_data(path):
    parts = [
        part.replace('\\', '/').lower()
        for part in path
        if isinstance(part, str)
    ] if isinstance(path, tuple) else [str(path).replace('\\', '/').lower()]

    for normalized in parts:
        basename = Path(normalized).name
        if basename in _strip_exact_data and '.dist-info/' in normalized:
            return True
        if any(fragment in normalized for fragment in _strip_path_fragments):
            return True
    return False


a.binaries = [b for b in a.binaries if not _should_strip(b[0])]

# Remove astropy test directories from collected data
a.datas = [
    d for d in a.datas
    if '/tests/' not in d[0].replace('\\', '/')
    and '/test/' not in d[0].replace('\\', '/')
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

