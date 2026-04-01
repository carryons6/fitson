"""Quick smoke test for FITSService.render()."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from astroview.core.fits_service import FITSService

path = sys.argv[1] if len(sys.argv) > 1 else "astroview/sample.fits"

svc = FITSService()
data = svc.open_file(path)
print("loaded:", data.data.shape, data.data.dtype)

for stretch in FITSService.AVAILABLE_STRETCHES:
    for interval in FITSService.AVAILABLE_INTERVALS:
        svc.set_stretch(stretch)
        svc.set_interval(interval)
        result = svc.render()
        assert result.image_u8 is not None
        assert result.image_u8.shape == (1024, 1024)
        assert result.image_u8.dtype.name == "uint8"
        lo, hi = result.image_u8.min(), result.image_u8.max()
        print(f"  {stretch:8s} + {interval:6s} -> [{lo:3d}, {hi:3d}]")

print("all combinations OK")
