from astropy.io import fits

path = "image1.fits"

with fits.open(path) as hdul:
    hdul.info()

    for hdu in hdul:
        print("\nHDU:", hdu.name)
        print("Shape:", getattr(hdu.data, "shape", None))

        if hdu.data is not None:
            print("CTYPE1:", hdu.header.get("CTYPE1"))
            print("CTYPE2:", hdu.header.get("CTYPE2"))