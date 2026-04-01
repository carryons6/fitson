"""Smoke test for SEPService.extract() + SourceCatalog."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from astroview.core.fits_data import FITSData
from astroview.core.sep_service import SEPService

path = sys.argv[1] if len(sys.argv) > 1 else "astroview/sample.fits"

data = FITSData.load(path)
svc = SEPService()
catalog = svc.extract(data.data, x_offset=0, y_offset=0, wcs=data.wcs)

print(f"detected {len(catalog)} sources")
rows = catalog.to_rows()
for row in rows[:5]:
    print(row)
if len(catalog) > 5:
    print(f"... and {len(catalog) - 5} more")
