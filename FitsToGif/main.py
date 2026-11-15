from pathlib import Path
import sys

# =====================================
# 1. KONFIGURACJA ŚCIEŻEK I FOLDERÓW
# =====================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]  # Folder NASA_Space_Apps_Challenge

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IMAGES_DIR = BASE_DIR / "images"
RESULTS_DIR = BASE_DIR / "results"
ALIGNED_DIR = RESULTS_DIR / "aligned"
GIF_DIR = RESULTS_DIR / "gifs"


def setup_folders() -> None:
    """Tworzy wymaganą strukturę folderów na samym początku."""
    for folder in [IMAGES_DIR, RESULTS_DIR, ALIGNED_DIR, GIF_DIR]:
        folder.mkdir(parents=True, exist_ok=True)


setup_folders()

# =====================================
# 2. IMPORT BIBLIOTEK
# =====================================

import numpy as np
import imageio.v2 as imageio
from astropy.io import fits
from astropy.visualization import ImageNormalize, PercentileInterval, AsinhStretch

from FitsTools.FitsToGif.alignment import align_to_reference


# =====================================
# 3. USTAWIENIA WIZUALNE (DO DOSTROJENIA)
# =====================================

# Procent pikseli używany do wyznaczenia zakresu jasności (np. 99.5 ucina skrajne 0.5% szumu i gwiazd)
PERCENTILE = 99.5

# Siła wyciągania słabych detali (zakres 0.01 - 0.5):
# - Mniejsza wartość (np. 0.02) = mocniej wyciąga ciemne mgławice i ogony komet
# - Większa wartość (np. 0.2) = mniejszy szum tła, bardziej naturalny kontrast
STRETCH_A = 0.05

# Czas trwania jednej klatki w milisekundach (200 ms = 5 klatek na sekundę)
FRAME_DURATION_MS = 200


# =====================================
# 4. FUNKCJE POMOCNICZE
# =====================================

def find_fits_files(directory: Path) -> list[Path]:
    """Znajduje wszystkie pliki FITS w podanym folderze."""
    extensions = {".fits", ".fit", ".fts"}
    files = [
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in extensions
    ]
    return sorted(files)


def load_image(path: Path) -> np.ndarray:
    """Wczytuje dane obrazu z pliku FITS jako tablicę float32."""
    with fits.open(path) as hdul:
        data = hdul["IMAGE"].data if "IMAGE" in hdul else hdul[0].data

        if data is None:
            raise ValueError(f"Brak danych obrazu w pliku: {path.name}")

        return np.asarray(data, dtype=np.float32)


def process_frames_for_gif(observations: list[np.ndarray]) -> list[np.ndarray]:
    """Wyrównuje jasność tła między klatkami i aplikuje astronomiczny AsinhStretch."""
    # 1. Wyrównanie poziomu tła (mediany) do pierwszej klatki, aby uniknąć mrugania
    ref_median = np.nanmedian(observations[0])
    matched_observations = []

    for img in observations:
        img_median = np.nanmedian(img)
        if np.isfinite(img_median) and np.isfinite(ref_median):
            matched_observations.append(img - (img_median - ref_median))
        else:
            matched_observations.append(img)

    # 2. Wyznaczenie globalnych progów jasności na podstawie klatki referencyjnej
    valid_ref = matched_observations[0][np.isfinite(matched_observations[0])]
    if valid_ref.size == 0:
        raise RuntimeError("Obraz referencyjny nie zawiera żadnych poprawnych pikseli!")

    interval = PercentileInterval(PERCENTILE)
    vmin, vmax = interval.get_limits(valid_ref)

    # 3. Nieliniowe rozciąganie histogramu (AsinhStretch)
    norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch(a=STRETCH_A))

    frames = []
    for img in matched_observations:
        # Krawędzie bez danych (NaN po alignmencie) wypełniamy wartością vmin (tłem)
        clean_img = np.where(np.isfinite(img), img, vmin)
        stretched = np.clip(norm(clean_img), 0.0, 1.0)
        frame_uint8 = (stretched * 255).astype(np.uint8)
        frames.append(frame_uint8)

    return frames


# =====================================
# 5. GŁÓWNY PROGRAM
# =====================================

def main() -> None:
    print(f"Katalog projektu: {BASE_DIR}")
    print(f"Foldery gotowe w: {RESULTS_DIR}\n")

    files = find_fits_files(IMAGES_DIR)

    if not files:
        print(f"[INFO] Brak plików FITS w folderze:\n  {IMAGES_DIR}")
        print("Wrzuć tam swoje pliki .fits i uruchom skrypt ponownie.")
        sys.exit(0)

    if len(files) < 2:
        print(f"[INFO] Znaleziono tylko 1 plik ({files[0].name}).")
        print("Potrzebujesz minimum 2 plików FITS, aby wykonać wyrównanie i stworzyć GIF.")
        sys.exit(0)

    reference_path = files[0]
    observation_files = files[1:]

    print(f"Obraz referencyjny: {reference_path.name}")
    print(f"Liczba klatek do wyrównania: {len(observation_files)}")

    print("\nWczytywanie obrazu referencyjnego...")
    reference = load_image(reference_path)
    observations = [reference]

    # Wyrównywanie kolejnych klatek
    for index, path in enumerate(observation_files, start=1):
        print(f"[{index}/{len(observation_files)}] Wyrównywanie: {path.name}...")
        output_path = ALIGNED_DIR / f"{path.stem}_aligned.fits"

        aligned, footprint = align_to_reference(
            str(path),
            str(reference_path),
            str(output_path)
        )

        # Maskowanie obszarów poza wspólnym polem widzenia
        aligned = np.where(footprint > 0, aligned, np.nan)
        observations.append(aligned)

    # Przetwarzanie wizualne i zapis GIF
    print("\nWyrównywanie tła i generowanie wysokiej jakości GIF-a...")
    frames = process_frames_for_gif(observations)

    gif_output_path = GIF_DIR / "aligned_timelapse.gif"
    imageio.mimsave(
        gif_output_path,
        frames,
        duration=FRAME_DURATION_MS,
        loop=0
    )

    print("\n================================")
    print("ZAKOŃCZONO SUKCESEM!")
    print("================================")
    print(f"Zapisany GIF:   {gif_output_path}")
    print(f"Wyrównane FITS: {ALIGNED_DIR}")
    print("================================")


if __name__ == "__main__":
    main()
