"""
Load SPHEREx spectral images covering a sky position into the astro_test schema.

SPHEREx data at IRSA are spectral images (not a source catalog), so the mapping is:
    data_sources       -> one row: SPHEREx Quick Release (IRSA)
    celestial_objects  -> one row: the target you searched for (name + position)
    observations       -> one row per spectral image covering the target
                          (observed_at = observation time, wavelength_band = detector,
                           data_url = the full multi-extension FITS file)
    images             -> one row per spectral image: link to a small FITS cutout
                          centred on the target

Usage:
    python ETL_spherex.py --name "M31" --ra 10.684 --dec 41.269
    python ETL_spherex.py --ra 10.684 --dec 41.269 --bands 2 4 --limit 50
    python ETL_spherex.py --ra 10.684 --dec 41.269 --size 100 --all-versions
"""
import argparse
import os

import pandas as pd
import psycopg2
from astroquery.ipac.irsa import Irsa
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
IRSA_BASE = "https://irsa.ipac.caltech.edu/"
SOURCE_NAME = "SPHEREx Quick Release Spectral Images"
SOURCE_PROVIDER = "NASA/IPAC Infrared Science Archive (IRSA)"
SOURCE_URL = "https://irsa.ipac.caltech.edu/Missions/spherex.html"
TARGET_TYPE = "sky target"  # the position the user asked about, not a catalogued star

# SPHEREx detector (D1..D6) -> wavelength range in micrometres
DETECTORS = {
    1: "0.75-1.1 um",
    2: "1.1-1.6 um",
    3: "1.6-2.4 um",
    4: "2.4-3.8 um",
    5: "3.8-4.4 um",
    6: "4.4-5.0 um",
}
DEFAULT_CUTOUT_SIZE = 50  # cutout size passed to IRSA's cutout service (pixels)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _mjd_to_ts(mjd: pd.Series) -> pd.Series:
    seconds = (pd.to_numeric(mjd, errors="coerce") - 40587.0) * 86400.0
    return pd.to_datetime(seconds, unit="s", utc=True)


def _ts(x):
    return None if pd.isna(x) else x.to_pydatetime()


def _decode_bytes(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.select_dtypes(include=["object", "string"]):
        df[col] = df[col].apply(lambda x: x.decode("utf-8") if isinstance(x, bytes) else x)
    return df


def _band_label(bandpass) -> str:
    """'SPHEREx-D2' -> 'SPHEREx D2 (1.1-1.6 um)'."""
    digits = "".join(ch for ch in str(bandpass).split("-")[-1] if ch.isdigit())
    if digits and int(digits) in DETECTORS:
        n = int(digits)
        return f"SPHEREx D{n} ({DETECTORS[n]})"
    return str(bandpass)


# --------------------------------------------------------------------------
# 1. EXTRACT
# --------------------------------------------------------------------------
def fetch_spectral_images(ra: float, dec: float, limit: int, bands, all_versions: bool) -> pd.DataFrame:
    band_filter = ""
    if bands:
        names = ", ".join(f"'SPHEREx-D{int(b)}'" for b in bands)
        band_filter = f"AND p.energy_bandpassname IN ({names})"

    adql = f"""
        SELECT TOP {int(limit)}
               a.uri AS uri,
               p.time_bounds_lower AS t_lo,
               p.time_bounds_upper AS t_hi,
               p.energy_bandpassname AS bandpass,
               p.provenance_version AS version
        FROM spherex.artifact a
        JOIN spherex.plane p ON a.planeid = p.planeid
        WHERE 1 = CONTAINS(POINT('ICRS', {ra}, {dec}), p.poly)
        {band_filter}
        ORDER BY p.time_bounds_lower
    """
    res = Irsa.query_tap(adql, async_job=True)
    tbl = res.to_table() if hasattr(res, "to_table") else res
    df = _decode_bytes(tbl.to_pandas())
    df.columns = [c.lower() for c in df.columns]
    if df.empty:
        return df

    # Reprocessed releases can contain the same exposure more than once:
    # keep the highest provenance version per (time, detector).
    if not all_versions and df["version"].nunique() > 1:
        before = len(df)
        df = (df.sort_values("version", ascending=False)
                .drop_duplicates(subset=["t_lo", "bandpass"], keep="first")
                .sort_values("t_lo"))
        print(f"Kept the latest processing version of each image "
              f"({before} -> {len(df)} rows). Use --all-versions to keep every version.")

    df = df.reset_index(drop=True)
    df["observed_at"] = _mjd_to_ts((pd.to_numeric(df["t_lo"], errors="coerce")
                                    + pd.to_numeric(df["t_hi"], errors="coerce")) / 2)
    df["band_label"] = df["bandpass"].apply(_band_label)
    df["file_url"] = df["uri"].apply(lambda u: u if str(u).startswith("http") else IRSA_BASE + str(u))
    return df


# --------------------------------------------------------------------------
# 2. LOAD
# --------------------------------------------------------------------------
def get_or_create_source(cur) -> int:
    cur.execute(
        "SELECT id FROM data_sources WHERE name = %s AND source_url = %s",
        (SOURCE_NAME, SOURCE_URL),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO data_sources (name, provider, source_url) VALUES (%s, %s, %s) RETURNING id",
        (SOURCE_NAME, SOURCE_PROVIDER, SOURCE_URL),
    )
    return cur.fetchone()[0]


def get_or_create_target(cur, name: str, ra: float, dec: float) -> tuple[int, bool]:
    cur.execute(
        "SELECT id FROM celestial_objects WHERE name = %s AND object_type = %s",
        (name, TARGET_TYPE),
    )
    row = cur.fetchone()
    if row:
        return row[0], False
    desc = (f"Sky position RA={ra:.6f}, Dec={dec:.6f} deg, searched in the SPHEREx "
            "Quick Release spectral images.")
    cur.execute(
        "INSERT INTO celestial_objects (name, object_type, nasa_identifier, description) "
        "VALUES (%s, %s, NULL, %s) RETURNING id",
        (name, TARGET_TYPE, desc),
    )
    return cur.fetchone()[0], True


def insert_observations(cur, df, obj_id, source_id, ra, dec) -> int:
    cur.execute(
        "SELECT data_url FROM observations WHERE object_id = %s AND source_id = %s",
        (obj_id, source_id),
    )
    existing = {r[0] for r in cur.fetchall()}  # makes re-runs idempotent

    rows = [
        (obj_id, source_id, _ts(r["observed_at"]), ra, dec, r["band_label"], r["file_url"])
        for _, r in df.iterrows()
        if r["file_url"] not in existing
    ]
    if rows:
        execute_values(
            cur,
            "INSERT INTO observations "
            "(object_id, source_id, observed_at, ra, dec, wavelength_band, data_url) VALUES %s",
            rows,
        )
    return len(rows)


def insert_images(cur, df, obj_id, source_id, name, ra, dec, size) -> int:
    cur.execute(
        "SELECT image_url FROM images WHERE object_id = %s AND source_id = %s",
        (obj_id, source_id),
    )
    existing = {r[0] for r in cur.fetchall()}

    rows = []
    for _, r in df.iterrows():
        url = f"{r['file_url']}?center={ra},{dec}d&size={size}"
        if url in existing:
            continue
        when = _ts(r["observed_at"])
        stamp = when.strftime("%Y-%m-%d") if when else "unknown date"
        title = f"{r['band_label']} cutout - {name} - {stamp}"[:250]
        desc = (f"SPHEREx spectral image cutout (size {size}, centred on RA={ra:.5f}, Dec={dec:.5f}). "
                f"Multi-extension FITS: image, flags, variance, zodi, PSF, wavelength WCS. "
                f"Processing version: {r['version']}.")
        rows.append((obj_id, source_id, title, url, desc, when))
    if rows:
        execute_values(
            cur,
            "INSERT INTO images (object_id, source_id, title, image_url, description, captured_at) "
            "VALUES %s",
            rows,
        )
    return len(rows)


def connect():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_NAME"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASS"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
    )


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def ingest(ra: float, dec: float, name: str | None = None, limit: int = 200,
           bands=None, size: float = DEFAULT_CUTOUT_SIZE, all_versions: bool = False) -> dict:
    name = name or f"SPHEREx target {ra:.4f}{dec:+.4f}"

    df = fetch_spectral_images(ra, dec, limit, bands, all_versions)
    if df.empty:
        print("No SPHEREx spectral images cover this position (yet).")
        return {"images_found": 0, "observations": 0, "images": 0}

    first, last = df["observed_at"].min(), df["observed_at"].max()
    print(f"Found {len(df)} spectral images, observed {first:%Y-%m-%d} to {last:%Y-%m-%d}.")

    conn = connect()
    try:
        with conn.cursor() as cur:
            source_id = get_or_create_source(cur)
            obj_id, created = get_or_create_target(cur, name, ra, dec)
            n_obs = insert_observations(cur, df, obj_id, source_id, ra, dec)
            n_img = insert_images(cur, df, obj_id, source_id, name, ra, dec, size)
        conn.commit()  # one transaction: all or nothing
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Target '{name}' ({'new' if created else 'existing'}) | "
          f"new observations: {n_obs} | new images: {n_img}")
    return {"images_found": len(df), "observations": n_obs, "images": n_img}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Load SPHEREx spectral images for a position into PostgreSQL.")
    p.add_argument("--ra", type=float, default=10.684, help="Right ascension [deg]")
    p.add_argument("--dec", type=float, default=41.269, help="Declination [deg]")
    p.add_argument("--name", help="name of the target, e.g. 'M31' (default: built from coordinates)")
    p.add_argument("--limit", type=int, default=200, help="max spectral images to load (default 200)")
    p.add_argument("--bands", type=int, nargs="+", choices=sorted(DETECTORS),
                   help="only these SPHEREx detectors/bands (1-6)")
    p.add_argument("--size", type=float, default=DEFAULT_CUTOUT_SIZE,
                   help="cutout size sent to IRSA's cutout service (default 50)")
    p.add_argument("--all-versions", action="store_true",
                   help="keep every processing version of an image (default: latest only)")
    args = p.parse_args()
    ingest(args.ra, args.dec, args.name, args.limit, args.bands, args.size, args.all_versions)