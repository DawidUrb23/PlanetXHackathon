
import numpy as np


def crop_around_object(image, x, y, size=300):
    """
    Crop an image around a detected object.

    x, y: detected object's pixel coordinates
    size: output crop width and height
    """

    height, width = image.shape

    half = size // 2

    # Calculate crop boundaries
    x1 = round(x) - half
    y1 = round(y) - half
    x2 = x1 + size
    y2 = y1 + size

    # Calculate how much padding is needed
    pad_left = max(0, -x1)
    pad_top = max(0, -y1)
    pad_right = max(0, x2 - width)
    pad_bottom = max(0, y2 - height)

    # Keep boundaries inside original image
    x1_clip = max(0, x1)
    y1_clip = max(0, y1)
    x2_clip = min(width, x2)
    y2_clip = min(height, y2)

    cropped = image[
        y1_clip:y2_clip,
        x1_clip:x2_clip
    ]

    # Add padding to maintain identical dimensions
    cropped = np.pad(
        cropped,
        ((pad_top, pad_bottom), (pad_left, pad_right)),
        mode="constant",
        constant_values=np.nan
    )

    return cropped
