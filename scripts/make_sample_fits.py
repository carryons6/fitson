"""Generate a sample FITS file with synthetic stars on a noisy background."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS


def make_background(shape: tuple[int, int], sky: float = 200.0, noise: float = 15.0) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.normal(loc=sky, scale=noise, size=shape).astype(np.float32)


def add_gaussian_star(
    image: np.ndarray, cx: float, cy: float, flux: float, fwhm: float = 4.0
) -> None:
    sigma = fwhm / 2.355
    size = int(6 * sigma)
    y0, y1 = max(0, int(cy) - size), min(image.shape[0], int(cy) + size + 1)
    x0, x1 = max(0, int(cx) - size), min(image.shape[1], int(cx) + size + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    model = flux * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2))
    image[y0:y1, x0:x1] += model.astype(np.float32)


def make_wcs(shape: tuple[int, int]) -> WCS:
    w = WCS(naxis=2)
    w.wcs.crpix = [shape[1] / 2, shape[0] / 2]
    w.wcs.crval = [180.0, 45.0]
    w.wcs.cdelt = [-2.78e-4, 2.78e-4]  # ~1 arcsec/pixel
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w


def generate(output: Path, width: int = 1024, height: int = 1024, n_stars: int = 80) -> None:
    image = make_background((height, width))

    rng = np.random.default_rng(123)
    for _ in range(n_stars):
        cx = rng.uniform(20, width - 20)
        cy = rng.uniform(20, height - 20)
        flux = rng.uniform(500, 30000)
        fwhm = rng.uniform(2.5, 6.0)
        add_gaussian_star(image, cx, cy, flux, fwhm)

    wcs = make_wcs((height, width))
    header = wcs.to_header()
    header["OBJECT"] = "Synthetic Field"
    header["INSTRUME"] = "AstroView Sample Generator"
    header["BUNIT"] = "ADU"

    hdu = fits.PrimaryHDU(data=image, header=header)
    hdu.writeto(output, overwrite=True)
    print(f"Written: {output}  ({width}x{height}, {n_stars} stars)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a sample FITS file.")
    parser.add_argument("-o", "--output", default="sample.fits", help="Output path (default: sample.fits)")
    parser.add_argument("--width", type=int, default=8 * 1024)
    parser.add_argument("--height", type=int, default=8 * 1024)
    parser.add_argument("--stars", type=int, default=80 * 64)
    args = parser.parse_args()
    generate(Path(args.output), args.width, args.height, args.stars)


if __name__ == "__main__":
    main()
