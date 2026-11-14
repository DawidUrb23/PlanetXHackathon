
import numpy as np


def detect_changes(difference, threshold=5):

    # Ignore invalid pixels
    valid = np.isfinite(difference)

    values = difference[valid]

    if values.size == 0:
        raise ValueError("No valid pixels to analyze")

    # Calculate background level
    median = np.median(values)

    # Estimate noise using MAD
    mad = np.median(np.abs(values - median))
    sigma = 1.4826 * mad

    if sigma == 0:
        raise ValueError("Noise estimate is zero")

    # Calculate significance
    significance = np.full(
        difference.shape,
        np.nan,
        dtype=np.float32
    )

    significance[valid] = (
        difference[valid] - median
    ) / sigma

    # Find significant differences
    mask = (
        valid &
        (np.abs(significance) > threshold)
    )

    return mask, significance
