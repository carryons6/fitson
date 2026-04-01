"""Quick smoke test for FITSData.load()."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from astroview.core.fits_data import FITSData

path = sys.argv[1] if len(sys.argv) > 1 else "astroview/sample.fits"
d = FITSData.load(path)
print("path:", d.path)
print("hdu_index:", d.hdu_index)
print("data shape:", d.data.shape, d.data.dtype)
print("has_wcs:", d.has_wcs)
print("available_hdus:", d.available_hdus)
print("header (first 200):", d.header_as_text()[:200])
print("sample(512,512):", d.sample_pixel(512, 512))
print("sample(-1,-1):", d.sample_pixel(-1, -1))
