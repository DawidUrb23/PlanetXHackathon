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

        image = image_hdu.data.astype(np.float32)
        header = image_hdu.header.copy()

        wcs = WCS(header)

    if image.ndim != 2:
        raise ValueError(f"Obraz nie jest 2D: {image.shape}")

    if not wcs.has_celestial:
        raise ValueError("Brak współrzędnych astronomicznych WCS")

    return image, wcs, header