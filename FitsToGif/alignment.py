import numpy as np

from astropy.io import fits
from astropy.wcs import WCS
from reproject import reproject_interp
from FitsTools.FitsToGif.fits_loader import load_image
from pathlib import Path

def align_folder(folder, reference_path):

    folder = Path(folder)

    output_folder = folder / "aligned"
    output_folder.mkdir(exist_ok=True)

    files = list(folder.glob("*.fits"))

    for file in files:

        if file.resolve() == Path(reference_path).resolve():
            continue

        output = output_folder / file.name

        try:
            print(f"\nProcessing: {file.name}")

            align_to_reference(
                str(file),
                str(reference_path),
                str(output)
            )

        except Exception as error:
            print(f"Error: {error}")


def align_to_reference(
    moving_path,
    reference_path,
    output_path
):

    reference, ref_wcs, ref_header = load_image(
        reference_path
    )

    moving, moving_wcs, moving_header = load_image(
        moving_path
    )

    aligned, footprint = reproject_interp(
        (moving, moving_wcs),
        ref_wcs,
        shape_out=reference.shape,
        order="bilinear"
    )

    output_header = ref_header.copy()

    output_header.update(ref_wcs.to_header())

    fits.writeto(
        output_path,
        aligned.astype(np.float32),
        output_header,
        overwrite=True
    )

    print("Alignment completed!")
    print("Output:", output_path)

    return aligned, footprint
