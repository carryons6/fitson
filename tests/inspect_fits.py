from astropy.io import fits
hdul = fits.open('G:/BD-Tongbu/7851/001402/1.FITS')
print('Number of HDUs:', len(hdul))
for i, hdu in enumerate(hdul):
    tp = type(hdu).__name__
    has_data = hdu.data is not None
    print(f'HDU {i}: type={tp}, name={hdu.name}, has_data={has_data}')
    if has_data:
        print(f'  shape={hdu.data.shape}, ndim={hdu.data.ndim}, dtype={hdu.data.dtype}')
    print(f'  PrimaryHDU={isinstance(hdu, fits.PrimaryHDU)}, ImageHDU={isinstance(hdu, fits.ImageHDU)}, CompImageHDU={isinstance(hdu, fits.CompImageHDU)}')
hdul.close()
