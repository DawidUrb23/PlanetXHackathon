
from pathlib import Path
import csv
import json
import numpy as np
import matplotlib.pyplot as plt
import imageio.v2 as imageio
from scipy.ndimage import label
from fits_loader import load_image
from alignment import align_to_reference
from comparison import calculate_difference
from detection import detect_changes
from cropping import crop_around_object

BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"
RESULTS_DIR = BASE_DIR / "results"

ALIGNED_DIR = RESULTS_DIR / "aligned"
DIFFERENCES_DIR = RESULTS_DIR / "differences"
MASKS_DIR = RESULTS_DIR / "detections"
GIF_DIR = RESULTS_DIR / "gifs"
REPORTS_DIR = RESULTS_DIR / "reports"
TABLES_DIR = RESULTS_DIR / "tables"

REFERENCE_PATH = IMAGES_DIR / "reference.fits"

DETECTION_THRESHOLD = 5
MIN_OBJECT_PIXELS = 3
TRACK_MAX_DISTANCE = 8

for directory in [
    RESULTS_DIR,
    ALIGNED_DIR,
    DIFFERENCES_DIR,
    MASKS_DIR,
    GIF_DIR,
    REPORTS_DIR,
    TABLES_DIR
]:
    directory.mkdir(parents=True, exist_ok=True)


def clean_results():
    """Remove previous generated results before a new analysis."""

    import shutil

    folders_to_clean = [
        ALIGNED_DIR,
        DIFFERENCES_DIR,
        MASKS_DIR,
        GIF_DIR,
        REPORTS_DIR,
        TABLES_DIR
    ]

    print("\nCleaning previous results...")

    for folder in folders_to_clean:

        if folder.exists():
            shutil.rmtree(folder)

        folder.mkdir(parents=True, exist_ok=True)

        print(f"Cleaned: {folder.name}/")

    print("Cleanup completed!\n")
    
    
clean_results()

   
def normalize_image(image, low, high):
    """Convert a scientific image into an 8-bit GIF frame."""

    image = np.asarray(image, dtype=np.float32)

    result = np.zeros(image.shape, dtype=np.uint8)

    valid = np.isfinite(image)

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


def extract_candidates(mask, significance, min_pixels=3):
    """Group neighboring detected pixels into candidate regions."""

    structure = np.ones((3, 3), dtype=int)

    labels, number = label(mask, structure=structure)

    candidates = []

    for object_number in range(1, number + 1):

        ys, xs = np.where(labels == object_number)

        if len(xs) < min_pixels:
            continue

        values = significance[ys, xs]

        peak_index = np.nanargmax(np.abs(values))

        candidates.append({
            "x": float(np.mean(xs)),
            "y": float(np.mean(ys)),
            "pixels": int(len(xs)),
            "peak_significance": float(values[peak_index]),
            "peak_abs_significance": float(
                abs(values[peak_index])
            )
        })

    return candidates


def match_tracks(all_candidates, max_distance=8):
    """Basic nearest-neighbor tracking between consecutive comparisons."""

    tracks = []
    next_id = 1

    for frame_index, candidates in enumerate(all_candidates):

        available_tracks = [
            track for track in tracks
            if track["observations"][-1]["frame_index"] == frame_index - 1
        ]

        used_tracks = set()

        for candidate in candidates:

            best_track = None
            best_distance = max_distance

            for track in available_tracks:

                if track["track_id"] in used_tracks:
                    continue

                previous = track["observations"][-1]

                distance = np.hypot(
                    candidate["x"] - previous["x"],
                    candidate["y"] - previous["y"]
                )

                if distance < best_distance:
                    best_distance = distance
                    best_track = track

            observation = {
                **candidate,
                "frame_index": frame_index
            }

            if best_track is not None:
                best_track["observations"].append(observation)
                used_tracks.add(best_track["track_id"])

            else:
                tracks.append({
                    "track_id": next_id,
                    "observations": [observation]
                })
                next_id += 1

    return tracks


def save_candidates_csv(candidates, output_path):

    fieldnames = [
        "comparison",
        "candidate_id",
        "x",
        "y",
        "pixels",
        "peak_significance",
        "peak_abs_significance"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as file:

        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for candidate in candidates:
            writer.writerow(candidate)



print("\n=== SPHEREx ANALYZER ===")

print("\nLoading reference...")

reference, ref_wcs, ref_header = load_image(
    str(REFERENCE_PATH)
)



image_paths = sorted(
    path for path in IMAGES_DIR.glob("*.fits")
    if path != REFERENCE_PATH
)

if not image_paths:
    raise RuntimeError("No observation FITS files found!")

print(f"Found {len(image_paths)} observations.")


observations = []

observations.append({
    "name": REFERENCE_PATH.stem,
    "image": reference,
    "footprint": np.isfinite(reference).astype(np.float32)
})

for path in image_paths:

    print(f"Aligning {path.name}...")

    output_path = ALIGNED_DIR / f"{path.stem}_aligned.fits"

    aligned, footprint = align_to_reference(
        str(path),
        str(REFERENCE_PATH),
        str(output_path)
    )

    observations.append({
        "name": path.stem,
        "image": aligned,
        "footprint": footprint
    })



all_candidates = []
all_difference_frames = []

candidate_counter = 1
flat_candidates = []

for i in range(1, len(observations)):

    previous = observations[i - 1]
    current = observations[i]

    previous_name = previous["name"]
    current_name = current["name"]

    print(f"\nComparing {previous_name} -> {current_name}")

    common_footprint = (
        (previous["footprint"] > 0) &
        (current["footprint"] > 0)
    )

    difference = calculate_difference(
        previous["image"],
        current["image"],
        common_footprint
    )

    try:
        mask, significance = detect_changes(
            difference,
            threshold=DETECTION_THRESHOLD
        )

    except ValueError as error:
        print("Detection skipped:", error)
        all_candidates.append([])
        continue

    print("Candidate pixels:", np.count_nonzero(mask))

    candidates = extract_candidates(mask, significance)
    flat_candidates.extend(candidates)

    for candidate in candidates:
        candidate["comparison"] = (
            f"{previous_name}_to_{current_name}"
        )
        candidate["candidate_id"] = candidate_counter
        candidate_counter += 1

    all_candidates.append(candidates)

    print("Candidate regions:", len(candidates))

    # Save difference image
    difference_path = (
        DIFFERENCES_DIR /
        f"{previous_name}_to_{current_name}.fits"
    )

    from astropy.io import fits

    fits.PrimaryHDU(difference).writeto(
        difference_path,
        overwrite=True
    )

    # Save detection mask
    plt.imsave(
        MASKS_DIR /
        f"{previous_name}_to_{current_name}_mask.png",
        mask,
        cmap="gray"
    )

    # Save comparison plot
    valid = np.isfinite(difference)

    if np.any(valid):

        limit = np.nanpercentile(
            np.abs(difference[valid]),
            99
        )

        if not np.isfinite(limit) or limit == 0:
            limit = 1

        fig, axes = plt.subplots(1, 3, figsize=(16, 5))

        axes[0].imshow(
            previous["image"],
            origin="lower",
            cmap="gray"
        )
        axes[0].set_title(previous_name)

        axes[1].imshow(
            current["image"],
            origin="lower",
            cmap="gray"
        )
        axes[1].set_title(current_name)

        axes[2].imshow(
            difference,
            origin="lower",
            cmap="coolwarm",
            vmin=-limit,
            vmax=limit
        )
        axes[2].set_title("Difference")

        plt.tight_layout()

        plt.savefig(
            DIFFERENCES_DIR /
            f"{previous_name}_to_{current_name}.png",
            dpi=150
        )

        plt.close(fig)

    all_difference_frames.append(difference)


print("\nTracking candidates...")

tracks = match_tracks(
    all_candidates,
    max_distance=TRACK_MAX_DISTANCE
)

print("Tracks created:", len(tracks))


flat_candidates = [
    candidate
    for frame in all_candidates
    for candidate in frame
]

save_candidates_csv(
    flat_candidates,
    TABLES_DIR / "candidates.csv"
)



print("\nCreating sky timelapse GIF...")

all_images = [
    observation["image"]
    for observation in observations
]

valid_values = np.concatenate([
    image[np.isfinite(image)]
    for image in all_images
    if np.any(np.isfinite(image))
])

if valid_values.size:

    low, high = np.percentile(valid_values, [1, 99])

    # =================================
    # 1. FULL SKY TIMELAPSE
    # =================================

    sky_frames = [
        normalize_image(image, low, high)
        for image in all_images
    ]

    imageio.mimsave(
        GIF_DIR / "sky_timelapse.gif",
        sky_frames,
        duration=2,
        loop=0
    )

    # =================================
    # 2. CHANGES ONLY
    # =================================

    changes_frames = [
        normalize_image(image, low, high)
        for image in all_difference_frames
    ]

    imageio.mimsave(
        GIF_DIR / "changes_only.gif",
        changes_frames,
        duration=2,
        loop=0
    )

    # =================================
    # 3. OBJECT TIMELAPSE
    # =================================

    selected_track = next(
        (track for track in tracks
         if track["track_id"] == 14),
        None
    )

    if selected_track:

        observations = sorted(
            selected_track["observations"],
            key=lambda obs: obs["frame_index"]
        )

        object_frames = []

        for observation in observations:

            frame_index = observation["frame_index"]

            image = all_images[frame_index]

            cropped = crop_around_object(
                image,
                x=observation["x"],
                y=observation["y"],
                size=300
            )

            object_frames.append(
                normalize_image(cropped, low, high)
            )

        imageio.mimsave(
            GIF_DIR / "object_timelapse.gif",
            object_frames,
            duration=2,
            loop=0
        )

print("Observations:", len(observations))
print("Candidates:", len(flat_candidates))
print("Tracks:", len(tracks))

print("Results folder:", RESULTS_DIR)
