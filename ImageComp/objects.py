
import numpy as np
from scipy import ndimage


def find_objects(mask, significance, min_pixels=3):

    structure = np.ones((3, 3), dtype=int)

    labels, number_of_objects = ndimage.label(
        mask,
        structure=structure
    )

    objects = []

    for object_id in range(1, number_of_objects + 1):

        y_pixels, x_pixels = np.where(
            labels == object_id
        )

        pixel_count = len(x_pixels)

        if pixel_count < min_pixels:
            continue

        values = np.abs(
            significance[y_pixels, x_pixels]
        )

        if np.sum(values) > 0:
            x_center = np.average(x_pixels, weights=values)
            y_center = np.average(y_pixels, weights=values)
        else:
            x_center = np.mean(x_pixels)
            y_center = np.mean(y_pixels)

        objects.append({
            "object_id": object_id,
            "x": float(x_center),
            "y": float(y_center),
            "pixels": int(pixel_count),
            "peak_significance": float(np.max(values))
        })

    return objects
