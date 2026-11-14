import os
import json
import io
import gzip
import urllib.request
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
from skyfield.api import Loader
from skyfield.data import hipparcos
from astropy.coordinates import SkyCoord

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("setup_data")

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Common names for notable Messier objects
MESSIER_NAMES = {
    1: "Crab Nebula",
    2: "Messier 2",
    3: "Messier 3",
    4: "Messier 4",
    5: "Rose Cluster",
    6: "Butterfly Cluster",
    7: "Ptolemy Cluster",
    8: "Lagoon Nebula",
    9: "Messier 9",
    10: "Messier 10",
    11: "Wild Duck Cluster",
    12: "Messier 12",
    13: "Great Hercules Cluster",
    14: "Messier 14",
    15: "Great Pegasus Cluster",
    16: "Eagle Nebula",
    17: "Omega Nebula",
    18: "Black Swan Cluster",
    19: "Messier 19",
    20: "Trifid Nebula",
    21: "Webb's Cross",
    22: "Sagittarius Cluster",
    23: "Messier 23",
    24: "Sagittarius Star Cloud",
    25: "Messier 25",
    26: "Messier 26",
    27: "Dumbbell Nebula",
    28: "Messier 28",
    29: "Cooling Tower",
    30: "Messier 30",
    31: "Andromeda Galaxy",
    32: "Le Gentil",
    33: "Triangulum Galaxy",
    34: "Spiral Cluster",
    35: "Messier 35",
    36: "Pinwheel Cluster",
    37: "Messier 37",
    38: "Starfish Cluster",
    39: "Messier 39",
    40: "Winnecke 4",
    41: "Little Beehive Cluster",
    42: "Orion Nebula",
    43: "De Mairan's Nebula",
    44: "Beehive Cluster",
    45: "Pleiades",
    46: "Messier 46",
    47: "Messier 47",
    48: "Messier 48",
    49: "Messier 49",
    50: "Heart-Shaped Cluster",
    51: "Whirlpool Galaxy",
    52: "Scorpion Cluster",
    53: "Messier 53",
    54: "Messier 54",
    55: "Specter Cluster",
    56: "Messier 56",
    57: "Ring Nebula",
    58: "Messier 58",
    59: "Messier 59",
    60: "Messier 60",
    61: "Swirling Galaxy",
    62: "Flickering Globular",
    63: "Sunflower Galaxy",
    64: "Black Eye Galaxy",
    65: "Leo Triplet Member 1",
    66: "Leo Triplet Member 2",
    67: "King Cobra Cluster",
    68: "Messier 68",
    69: "Messier 69",
    70: "Messier 70",
    71: "Angelfish Cluster",
    72: "Messier 72",
    73: "Messier 73",
    74: "Phantom Galaxy",
    75: "Messier 75",
    76: "Little Dumbbell Nebula",
    77: "Cetus A",
    78: "Messier 78",
    79: "Messier 79",
    80: "Messier 80",
    81: "Bode's Galaxy",
    82: "Cigar Galaxy",
    83: "Southern Pinwheel Galaxy",
    84: "Messier 84",
    85: "Messier 85",
    86: "Messier 86",
    87: "Virgo A",
    88: "Messier 88",
    89: "Messier 89",
    90: "Messier 90",
    91: "Messier 91",
    92: "Messier 92",
    93: "Starfish Cluster",
    94: "Cat's Eye Galaxy",
    95: "Messier 95",
    96: "Messier 96",
    97: "Owl Nebula",
    98: "Messier 98",
    99: "Coma Pinwheel",
    100: "Mirror Galaxy",
    101: "Pinwheel Galaxy",
    102: "Spindle Galaxy",
    103: "Messier 103",
    104: "Sombrero Galaxy",
    105: "Messier 105",
    106: "Messier 106",
    107: "Messier 107",
    108: "Surfboard Galaxy",
    109: "Vacuum Cleaner Galaxy",
    110: "Edward Young Star",
}


def download_ephemeris():
    logger.info("1/3 Downloading de421.bsp ephemeris...")
    target_path = DATA_DIR / "de421.bsp"
    if target_path.exists():
        logger.info(f"de421.bsp already exists at {target_path} ({target_path.stat().st_size / (1024*1024):.2f} MB)")
        return
    loader = Loader(str(DATA_DIR))
    loader("de421.bsp")
    if target_path.exists():
        logger.info(f"de421.bsp ready at {target_path} ({target_path.stat().st_size / (1024*1024):.2f} MB)")
    else:
        raise FileNotFoundError(f"Failed to ensure {target_path}")


def download_hipparcos():
    logger.info("2/3 Downloading and filtering Hipparcos star catalog...")
    stars_csv_path = DATA_DIR / "stars_bright.csv"
    if stars_csv_path.exists():
        logger.info(f"stars_bright.csv already exists at {stars_csv_path}")
        return

    # Try standard URL or fallback to Skyfield official repository mirror
    df = None
    urls_to_try = [
        hipparcos.URL,
        "https://raw.githubusercontent.com/skyfielders/python-skyfield/master/ci/hip_main.dat.gz",
        "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat.gz",
    ]

    for url in urls_to_try:
        try:
            logger.info(f"Attempting to download Hipparcos data from: {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Skyfield backend)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if url.endswith(".gz"):
                    with gzip.open(io.BytesIO(data)) as f:
                        df = hipparcos.load_dataframe(f)
                else:
                    with io.StringIO(data.decode("ascii", errors="ignore")) as f:
                        df = hipparcos.load_dataframe(f)
            logger.info(f"Successfully parsed Hipparcos catalog ({len(df)} total stars)")
            break
        except Exception as e:
            logger.warning(f"Could not load from {url}: {e}")

    if df is None:
        raise RuntimeError("Failed to download Hipparcos catalog from all mirrors.")

    # Filter to magnitude <= 6.0 (naked-eye visible) and drop missing positions
    df_bright = df[df["magnitude"] <= 6.0].dropna(subset=["ra_degrees", "dec_degrees"])
    df_bright["parallax_mas"] = df_bright["parallax_mas"].fillna(0.0)
    df_bright["ra_mas_per_year"] = df_bright["ra_mas_per_year"].fillna(0.0)
    df_bright["dec_mas_per_year"] = df_bright["dec_mas_per_year"].fillna(0.0)
    logger.info(f"Filtered to {len(df_bright)} bright stars (magnitude <= 6.0, valid coordinates)")
    df_bright.to_csv(stars_csv_path, index=True)
    logger.info(f"Saved {stars_csv_path} ({stars_csv_path.stat().st_size / 1024:.1f} KB)")


def fetch_messier_object(num: int):
    m_id = f"M{num}"
    name = MESSIER_NAMES.get(num, f"Messier {num}")
    try:
        coord = SkyCoord.from_name(m_id)
        return {
            "id": m_id,
            "name": name,
            "ra_hours": float(coord.ra.hour),
            "dec_degrees": float(coord.dec.deg),
        }
    except Exception as e:
        logger.warning(f"Failed to query {m_id} from_name: {e}")
        return None


def download_messier():
    logger.info("3/3 Downloading Messier catalog coordinates (M1-M110)...")
    messier_path = DATA_DIR / "messier.json"
    if messier_path.exists():
        logger.info(f"messier.json already exists at {messier_path}")
        return

    objects = []
    # Use concurrent queries for performance
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_num = {executor.submit(fetch_messier_object, i): i for i in range(1, 111)}
        for future in as_completed(future_to_num):
            res = future.result()
            if res:
                objects.append(res)

    # Sort by Messier ID number
    objects.sort(key=lambda x: int(x["id"][1:]))
    logger.info(f"Successfully retrieved {len(objects)} / 110 Messier objects")

    with open(messier_path, "w", encoding="utf-8") as f:
        json.dump(objects, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {messier_path}")


if __name__ == "__main__":
    download_ephemeris()
    download_hipparcos()
    download_messier()
    logger.info("All astronomical datasets successfully prepared in data/")
