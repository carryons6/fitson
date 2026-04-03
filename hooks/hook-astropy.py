from PyInstaller.utils.hooks import collect_data_files, copy_metadata, is_module_satisfies


# Astropy needs bundled data files at runtime. The stock contrib hook uses
# collect_submodules('astropy'), but that isolated scan crashes in this conda
# environment. Enumerate submodules from the package directory instead.
datas = collect_data_files('astropy')

ply_files = []
for path, target in collect_data_files('astropy', include_py_files=True):
    if path.endswith(('_parsetab.py', '_lextab.py')):
        ply_files.append((path, target))

datas += ply_files

if is_module_satisfies('astropy >= 5.0'):
    datas += copy_metadata('astropy')
    datas += copy_metadata('numpy')

# The app uses only a narrow astropy surface: FITS I/O, compressed image HDUs,
# WCS, visualization stretches/intervals, and coordinate/unit conversion.
# Keeping the hook on that subset avoids pulling in most of astropy's optional
# subpackages, tests, and their transitive baggage.
hiddenimports = [
    'astropy.constants',
    'astropy.constants.cgs',
    'astropy.constants.codata2018',
    'astropy.constants.config',
    'astropy.constants.constant',
    'astropy.constants.iau2015',
    'astropy.constants.si',
    'astropy.constants.utils',
    'astropy.coordinates',
    'astropy.io.fits',
    'astropy.io.fits.hdu.compressed',
    'astropy.io.fits.hdu.compressed._codecs',
    'astropy.io.fits.hdu.compressed._compression',
    'astropy.io.fits.hdu.compressed._quantization',
    'astropy.io.fits.hdu.compressed._tiled_compression',
    'astropy.io.fits.hdu.compressed.compbintable',
    'astropy.io.fits.hdu.compressed.compressed',
    'astropy.io.fits.hdu.compressed.header',
    'astropy.io.fits.hdu.compressed.section',
    'astropy.io.fits.hdu.compressed.settings',
    'astropy.io.fits.hdu.compressed.utils',
    'astropy.units',
    'astropy.utils.xml._iterparser',
    'astropy.visualization',
    'astropy.wcs',
    'astropy.wcs.wcs',
    'astropy_iers_data',
    'numpy.lib.recfunctions',
    'yaml',
]
