
import numpy as np


def calculate_difference(
    reference,
    aligned,
    footprint,
    min_footprint=0.99,
    subtract_background=True
):
    reference = np.asarray(reference, dtype=np.float32)
    aligned = np.asarray(aligned, dtype=np.float32)
    footprint = np.asarray(footprint)

    if reference.shape != aligned.shape:
        raise ValueError("Images have different shapes")

    if reference.shape != footprint.shape:
        raise ValueError("Footprint has a different shape")

    # Find valid pixels
    valid = (
        np.isfinite(reference) &
        np.isfinite(aligned) &
        np.isfinite(footprint) &
        (footprint >= min_footprint)
    )

    if not np.any(valid):
        raise ValueError("No valid pixels to compare")

    # Calculate raw difference
    difference = np.full(
        reference.shape,
        np.nan,
        dtype=np.float32
    )

    difference[valid] = (
        reference[valid] - aligned[valid]
    )

    # Estimate global background offset
    background_offset = 0.0

    if subtract_background:
        background_offset = float(
            np.median(difference[valid])
        )

        difference[valid] -= background_offset

    return difference
