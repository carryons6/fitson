from PyInstaller.utils.hooks import collect_data_files, copy_metadata, is_module_satisfies


# Astropy needs bundled data files at runtime. Keep the collection broad enough
# for FITS/WCS/coordinates use, but exclude clearly irrelevant developer
# assets, optional datasets, and generated sources.
datas = collect_data_files(
    "astropy",
    excludes=[
        "**/tests/**",
        "**/test/**",
        "**/extern/jquery/**",
        "**/io/votable/**",
        "**/cosmology/data/**",
        "**/samp/**",
        "**/table/**",
        "**/timeseries/**",
        "**/stats/src/**",
        "**/convolution/src/**",
        "**/io/ascii/src/**",
        "**/utils/xml/src/**",
        "**/wcs/include/**",
        "**/*.pyx",
        "**/*.c",
        "**/*.h",
    ],
)

ply_files = []
for path, target in collect_data_files("astropy", include_py_files=True):
    if path.endswith(("_parsetab.py", "_lextab.py")):
        ply_files.append((path, target))

datas += ply_files

if is_module_satisfies("astropy >= 5.0"):
    datas += copy_metadata("astropy")
    datas += copy_metadata("numpy")

# The app uses only a narrow astropy surface: FITS I/O, compressed image HDUs,
# WCS, visualization stretches/intervals, and coordinate/unit conversion.
# Keeping the hook on that subset avoids pulling in most of astropy's optional
# subpackages, tests, and their transitive baggage.
hiddenimports = [
    "astropy.constants",
    "astropy.constants.cgs",
    "astropy.constants.codata2018",
    "astropy.constants.config",
    "astropy.constants.constant",
    "astropy.constants.iau2015",
    "astropy.constants.si",
    "astropy.constants.utils",
    "astropy.coordinates",
    "astropy.coordinates.errors",
    "astropy.coordinates.sky_coordinate",
    "astropy.io.fits",
    "astropy.io.fits.hdu.compressed",
    "astropy.io.fits.hdu.compressed._codecs",
    "astropy.io.fits.hdu.compressed._compression",
    "astropy.io.fits.hdu.compressed._quantization",
    "astropy.io.fits.hdu.compressed._tiled_compression",
    "astropy.io.fits.hdu.compressed.compressed",
    "astropy.io.fits.hdu.compressed.header",
    "astropy.io.fits.hdu.compressed.section",
    "astropy.io.fits.hdu.compressed.settings",
    "astropy.io.fits.hdu.compressed.utils",
    "astropy.table",
    "astropy.units",
    "astropy.utils.xml._iterparser",
    "astropy.visualization",
    "astropy.visualization.interval",
    "astropy.visualization.stretch",
    "astropy.wcs",
    "astropy.wcs.wcs",
    "astropy_iers_data",
    "yaml",
]
