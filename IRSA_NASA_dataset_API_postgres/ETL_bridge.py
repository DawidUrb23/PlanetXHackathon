"""
Query IRSA's AllWISE Source Catalog around given coordinates and load the
results into the astro_test schema (data_sources, celestial_objects,
observations).

Usage:
    python irsa_to_postgres.py --ra 10.684 --dec 41.269 --radius 0.1 --limit 100

Or from Python:
    from irsa_to_postgres import ingest
    ingest(ra=10.684, dec=41.269, radius_deg=0.1, row_limit=100)

Mapping:
    data_sources       -> one row for the AllWISE catalog (created once)
    celestial_objects  -> one row per WISE source (designation = nasa_identifier)
    observations       -> one row per source per detected band (W1..W4)
"""
import argparse
import os

import astropy.units as u
import pandas as pd
import psycopg2
from astropy.coordinates import SkyCoord
from astroquery.ipac.irsa import Irsa
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
CATALOG = "allwise_p3as_psd"
SOURCE_NAME = "AllWISE Source Catalog"
SOURCE_PROVIDER = "NASA/IPAC Infrared Science Archive (IRSA)"
SOURCE_URL = "https://irsa.ipac.caltech.edu/Missions/wise.html"
OBJECT_TYPE = "infrared source"  # AllWISE does not classify sources further

# WISE band -> label stored in observations.wavelength_band
BANDS = {
    "w1": "W1 (3.4 um)",
    "w2": "W2 (4.6 um)",
    "w3": "W3 (12 um)",
    "w4": "W4 (22 um)",
}

# The observations table has no column for the measured brightness, so by
# default the script adds two nullable columns for it. Set to False to leave
# your schema untouched (magnitudes then only appear in the object description).
STORE_MAGNITUDES = True

TARGET_COLS = (
    ["designation", "ra", "dec"]
    + [f"{b}mpro" for b in BANDS]
    + [f"{b}sigmpro" for b in BANDS]
)


# --------------------------------------------------------------------------
# 1. EXTRACT
# --------------------------------------------------------------------------
def fetch_sources(ra: float, dec: float, radius_deg: float, row_limit: int) -> pd.DataFrame:
    Irsa.ROW_LIMIT = row_limit
    coord = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
    cols = ",".join(TARGET_COLS)
    common = dict(catalog=CATALOG, spatial="Cone", radius=radius_deg * u.deg)

    try:
        # Current astroquery (TAP-based IRSA module)
        table = Irsa.query_region(coord, columns=cols, **common)
    except TypeError:
        # Older astroquery (Gator-based IRSA module)
        table = Irsa.query_region(coord, selcols=cols, async_job=True, **common)

    df = table.to_pandas()
    df.columns = [c.lower() for c in df.columns]
    if df.empty:
        return df

    df = df[TARGET_COLS]

    # Decode byte-strings if present
    for col in df.select_dtypes(include=["object", "string"]):
        df[col] = df[col].apply(lambda x: x.decode("utf-8") if isinstance(x, bytes) else x)

    df = df.drop_duplicates(subset="designation").reset_index(drop=True)

    # MJD -> timezone-aware timestamp (NaN -> NaT)
    # unix_seconds = (pd.to_numeric(df["mjd"], errors="coerce") - 40587.0) * 86400.0
    # df["observed_at"] = pd.to_datetime(unix_seconds, unit="s", utc=True)
    # The coadded AllWISE catalog has no per-source observation time
    df["observed_at"] = pd.NaT
    return df


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _f(x):
    """numpy/NaN -> plain float or None (psycopg2 cannot adapt numpy.float32)."""
    return None if pd.isna(x) else float(x)


def _ts(x):
    return None if pd.isna(x) else x.to_pydatetime()


def _gator_url(ra: float, dec: float) -> str:
    return (
        "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"
        f"?catalog={CATALOG}&spatial=Cone&objstr={ra:.6f}+{dec:.6f}"
        "&radius=5&radunits=arcsec&outfmt=1"
    )


def _describe(row) -> str:
    parts = [f"{label.split()[0]}={row[f'{b}mpro']:.3f}"
             for b, label in BANDS.items() if pd.notna(row[f"{b}mpro"])]
    mags = ", ".join(parts) if parts else "no band detections"
    return (f"AllWISE source at RA={row['ra']:.6f}, Dec={row['dec']:.6f} deg. "
            f"Profile-fit magnitudes (Vega): {mags}.")


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


def ensure_magnitude_columns(cur):
    cur.execute(
        "ALTER TABLE observations "
        "ADD COLUMN IF NOT EXISTS magnitude DOUBLE PRECISION, "
        "ADD COLUMN IF NOT EXISTS magnitude_error DOUBLE PRECISION"
    )


def upsert_objects(cur, df: pd.DataFrame) -> tuple[dict, int]:
    """Return ({designation: object_id}, number_of_new_objects)."""
    cur.execute(
        "SELECT nasa_identifier, id FROM celestial_objects "
        "WHERE object_type = %s AND nasa_identifier = ANY(%s)",
        (OBJECT_TYPE, df["designation"].tolist()),
    )
    ids = dict(cur.fetchall())

    new = df[~df["designation"].isin(ids)]
    if not new.empty:
        rows = [
            (f"WISE {r['designation']}", OBJECT_TYPE, r["designation"], _describe(r))
            for _, r in new.iterrows()
        ]
        inserted = execute_values(
            cur,
            "INSERT INTO celestial_objects (name, object_type, nasa_identifier, description) "
            "VALUES %s RETURNING nasa_identifier, id",
            rows,
            fetch=True,
        )
        ids.update(dict(inserted))
    return ids, len(new)


def insert_observations(cur, df: pd.DataFrame, ids: dict, source_id: int) -> int:
    cur.execute(
        "SELECT object_id, wavelength_band FROM observations "
        "WHERE source_id = %s AND object_id = ANY(%s)",
        (source_id, list(ids.values())),
    )
    existing = set(cur.fetchall())  # makes re-runs idempotent

    rows = []
    for _, r in df.iterrows():
        obj_id = ids[r["designation"]]
        url = _gator_url(r["ra"], r["dec"])
        for b, label in BANDS.items():
            mag = r[f"{b}mpro"]
            if pd.isna(mag) or (obj_id, label) in existing:
                continue  # no detection in this band, or already stored
            row = [obj_id, source_id, _ts(r["observed_at"]), _f(r["ra"]), _f(r["dec"]), label, url]
            if STORE_MAGNITUDES:
                row += [_f(mag), _f(r[f"{b}sigmpro"])]
            rows.append(tuple(row))

    if not rows:
        return 0

    cols = "object_id, source_id, observed_at, ra, dec, wavelength_band, data_url"
    if STORE_MAGNITUDES:
        cols += ", magnitude, magnitude_error"
    execute_values(cur, f"INSERT INTO observations ({cols}) VALUES %s", rows)
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
def ingest(ra: float, dec: float, radius_deg: float = 0.1, row_limit: int = 100) -> dict:
    df = fetch_sources(ra, dec, radius_deg, row_limit)
    if df.empty:
        print("No sources found for the given coordinates.")
        return {"sources": 0, "new_objects": 0, "observations": 0}

    conn = connect()
    try:
        with conn.cursor() as cur:
            if STORE_MAGNITUDES:
                ensure_magnitude_columns(cur)
            source_id = get_or_create_source(cur)
            ids, n_new = upsert_objects(cur, df)
            n_obs = insert_observations(cur, df, ids, source_id)
        conn.commit()  # one transaction: all or nothing
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"Fetched {len(df)} sources | new celestial_objects: {n_new} | "
        f"new observations: {n_obs}"
    )
    return {"sources": len(df), "new_objects": n_new, "observations": n_obs}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Load AllWISE sources around a position into PostgreSQL.")
    p.add_argument("--ra", type=float, default=10.684, help="Right ascension [deg]")
    p.add_argument("--dec", type=float, default=41.269, help="Declination [deg]")
    p.add_argument("--radius", type=float, default=0.1, help="Cone radius [deg]")
    p.add_argument("--limit", type=int, default=100, help="Max rows to fetch")
    args = p.parse_args()
    ingest(args.ra, args.dec, args.radius, args.limit) # THIS FUNCTION IS USED FOR LOADING THE DATA