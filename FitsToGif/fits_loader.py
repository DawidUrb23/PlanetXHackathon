import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

def load_fits(path):

    with fits.open(path) as hdul:

        data = {}

        for hdu in hdul:

            name = hdu.name

            if hdu.data is not None:
                data[name] = np.array(hdu.data)

        return data

def load_image(path):

    with fits.open(path) as hdul:

        image_hdu = hdul["IMAGE"]

        image = np.squeeze(
            image_hdu.data
        ).astype(np.float32)

        header = image_hdu.header.copy()

        wcs = WCS(header).celestial

    if image.ndim != 2:
        raise ValueError(
            f"Image is not 2D: {image.shape}"
        )

    if not wcs.has_celestial:
        raise ValueError(
            "Missing celestial WCS coordinates"
        )

    return image, wcs, header
