
from pathlib import Path

import numpy as np
import imageio.v2 as imageio

from astropy.io import fits
from FitsTools.FitsToGif.alignment import align_to_reference


# =====================================
# PATH CONFIGURATION
# =====================================

BASE_DIR = Path(__file__).resolve().parent

IMAGES_DIR = BASE_DIR / "images"
RESULTS_DIR = BASE_DIR / "results"

ALIGNED_DIR = RESULTS_DIR / "aligned"
GIF_DIR = RESULTS_DIR / "gifs"

ALIGNED_DIR.mkdir(parents=True, exist_ok=True)
GIF_DIR.mkdir(parents=True, exist_ok=True)


# =====================================
# FIND FITS FILES
# =====================================

files = sorted(IMAGES_DIR.glob("*.fits"))

if not files:
    raise RuntimeError(
        f"No FITS files found in: {IMAGES_DIR}"
    )

REFERENCE_PATH = files[0]
OBSERVATION_FILES = files[1:]

print(f"Project directory: {BASE_DIR}")
print(f"Reference: {REFERENCE_PATH.name}")
print(f"Observations: {len(OBSERVATION_FILES)}")


# =====================================
# LOAD IMAGE
# =====================================

def load_image(path):

    with fits.open(path) as hdul:

        if "IMAGE" in hdul:
            data = hdul["IMAGE"].data
        else:
            data = hdul[0].data

        if data is None:
            raise ValueError(f"No image data: {path}")

        return np.asarray(data, dtype=np.float32)


# =====================================
# NORMALIZATION
# =====================================

def normalize_image(image, low, high):

    valid = np.isfinite(image)

    result = np.zeros(image.shape, dtype=np.uint8)

    if not np.any(valid):
        return result

    if high <= low:
        high = low + 1

    normalized = np.clip(
        (image[valid] - low) / (high - low),
        0,
        1
    )

    result[valid] = (normalized * 255).astype(np.uint8)

    return result


# =====================================
# MAIN
# =====================================

def main():

    reference = load_image(REFERENCE_PATH)

    observations = [reference]

    # Align remaining FITS files
    for index, path in enumerate(OBSERVATION_FILES, 1):

        print(
            f"[{index}/{len(OBSERVATION_FILES)}] "
            f"Aligning {path.name}"
        )

        output_path = (
            ALIGNED_DIR / f"{path.stem}_aligned.fits"
        )

        aligned, footprint = align_to_reference(
            str(path),
            str(REFERENCE_PATH),
            str(output_path)
        )

        aligned = np.where(
            footprint > 0,
            aligned,
            np.nan
        )

        observations.append(aligned)

    print("Creating GIF...")

    valid_arrays = [
        img[np.isfinite(img)]
        for img in observations
        if np.any(np.isfinite(img))
    ]

    if not valid_arrays:
        raise RuntimeError("No valid image pixels found!")

    valid_values = np.concatenate(valid_arrays)

    low, high = np.percentile(valid_values, [1, 99])

    frames = [
        normalize_image(img, low, high)
        for img in observations
    ]

    output_path = GIF_DIR / "aligned_timelapse.gif"

    imageio.mimsave(
        output_path,
        frames,
        duration=10,
        loop=0
    )

    print("\n================================")
    print("GIF CREATED SUCCESSFULLY!")
    print(f"Output: {output_path}")
    print("================================")


if __name__ == "__main__":
    main()
