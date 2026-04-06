from PyInstaller.compat import is_pure_conda
from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs("numpy", ".")

if is_pure_conda:
    from PyInstaller.utils.hooks import conda_support
    datas = conda_support.collect_dynamic_libs("numpy", dependencies=True)

hiddenimports = [
    "numpy._core._dtype_ctypes",
    "numpy.core._multiarray_tests",
]

excludedimports = [
    "scipy",
    "pytest",
    "f2py",
    "setuptools",
    "distutils",
    "numpy.distutils",
]
