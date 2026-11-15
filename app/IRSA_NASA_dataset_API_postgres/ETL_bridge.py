"""
Query IRSA's AllWISE Source Catalog around given coordinates and load the
results into the astro_test schema, including links to AllWISE image cutouts.

Usage:
    python ETL_bridge.py --ra 10.684 --dec 41.269 --radius 0.1 --limit 100
    python ETL_bridge.py --no-images          # catalog data only
    python ETL_bridge.py --cutout 120         # 120" x 120" cutouts

Or from Python:
    from ETL_bridge import ingest
    ingest(ra=10.684, dec=41.269, radius_deg=0.1, row_limit=100)

Mapping:
    data_sources       -> one row for AllWISE (created once)
    celestial_objects  -> one row per WISE source (designation = nasa_identifier)
    observations       -> one row per source per detected band (W1..W4)
    images             -> one row per source per band (W1..W4): a link to an
                          IRSA FITS cutout centred on that source
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
IMAGE_COLLECTION = "wise_allwise"  # IRSA SIA collection with the AllWISE Atlas images
SOURCE_NAME = "AllWISE Source Catalog"
SOURCE_PROVIDER = "NASA/IPAC Infrared Science Archive (IRSA)"
SOURCE_URL = "https://irsa.ipac.caltech.edu/Missions/wise.html"
OBJECT_TYPE = "infrared source"  # AllWISE does not classify sources further

# WISE band -> (label stored in the DB, nominal wavelength in micrometres)
BANDS = {
    "w1": ("W1 (3.4 um)", 3.4),
    "w2": ("W2 (4.6 um)", 4.6),
    "w3": ("W3 (12 um)", 12.0),
    "w4": ("W4 (22 um)", 22.0),
}

DEFAULT_CUTOUT_ARCSEC = 60

# The observations table has no column for the measured brightness, so by
# default the script adds two nullable columns for it. Set to False to leave
# the schema untouched (magnitudes then only appear in the object description).
STORE_MAGNITUDES = True

TARGET_COLS = (
    ["designation", "ra", "dec"]
    + [f"{b}mpro" for b in BANDS]
    + [f"{b}sigmpro" for b in BANDS]
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _f(x):
    """numpy/NaN -> plain float or None (psycopg2 cannot adapt numpy.float32)."""
    return None if pd.isna(x) else float(x)


def _ts(x):
    return None if pd.isna(x) else x.to_pydatetime()


def _mjd_to_ts(mjd: pd.Series) -> pd.Series:
    seconds = (pd.to_numeric(mjd, errors="coerce") - 40587.0) * 86400.0
    return pd.to_datetime(seconds, unit="s", utc=True)


def _decode_bytes(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.select_dtypes(include=["object", "string"]):
        df[col] = df[col].apply(lambda x: x.decode("utf-8") if isinstance(x, bytes) else x)
    return df


def _gator_url(ra: float, dec: float) -> str:
    return (
        "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"
        f"?catalog={CATALOG}&spatial=Cone&objstr={ra:.6f}+{dec:.6f}"
        "&radius=5&radunits=arcsec&outfmt=1"
    )


def _cutout_url(tile_url: str, ra: float, dec: float, size_arcsec: float) -> str:
    sep = "&" if "?" in tile_url else "?"
    return f"{tile_url}{sep}center={ra:.6f},{dec:.6f}&size={size_arcsec:g}arcsec&gzip=false"


def _describe(row) -> str:
    parts = [f"{label.split()[0]}={row[f'{b}mpro']:.3f}"
             for b, (label, _) in BANDS.items() if pd.notna(row[f"{b}mpro"])]
    mags = ", ".join(parts) if parts else "no band detections"
    return (f"AllWISE source at RA={row['ra']:.6f}, Dec={row['dec']:.6f} deg. "
            f"Profile-fit magnitudes (Vega): {mags}.")


# --------------------------------------------------------------------------
# 1. EXTRACT: catalog sources
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

    df = _decode_bytes(df[TARGET_COLS])
    df = df.drop_duplicates(subset="designation").reset_index(drop=True)

    # The coadded AllWISE catalog has no per-source observation time
    df["observed_at"] = pd.NaT
    return df


# --------------------------------------------------------------------------
# 1b. EXTRACT: image tiles (IRSA Simple Image Access, SIA2)
# --------------------------------------------------------------------------
def fetch_image_tiles(ra: float, dec: float, radius_deg: float) -> pd.DataFrame:
    """
    Return the AllWISE Atlas science images covering the search cone, one row
    per tile, with columns: band, access_url, s_ra, s_dec, captured_at.
    """
    coord = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
    res = Irsa.query_sia(pos=(coord, radius_deg * u.deg), collection=IMAGE_COLLECTION)
    tbl = res.to_table() if hasattr(res, "to_table") else res

    lower = {c.lower(): c for c in tbl.colnames}
    required = ["access_url", "em_min", "em_max", "s_ra", "s_dec"]
    missing = [c for c in required if c not in lower]
    if missing:
        raise ValueError(f"SIA result lacks columns {missing}; available: {tbl.colnames}")

    optional = [c for c in ("dataproduct_subtype", "t_min", "t_max") if c in lower]
    df = tbl[[lower[c] for c in required + optional]].to_pandas()
    df.columns = [c.lower() for c in df.columns]
    df = _decode_bytes(df)

    # Keep science (intensity) images only; skip uncertainty / coverage maps
    if "dataproduct_subtype" in df:
        subtypes = sorted(df["dataproduct_subtype"].astype(str).unique())
        df = df[df["dataproduct_subtype"].astype(str).str.lower() == "science"]
        if df.empty:
            print(f"WARNING: no 'science' images in SIA result (subtypes seen: {subtypes}).")
    else:
        df = df[df["access_url"].astype(str).str.contains("-int-")]

    # Map each tile to a WISE band via its central wavelength (SIA2 gives metres)
    centre_um = (pd.to_numeric(df["em_min"], errors="coerce")
                 + pd.to_numeric(df["em_max"], errors="coerce")) / 2 * 1e6

    def pick_band(c):
        if pd.isna(c):
            return None
        best = min(BANDS, key=lambda b: abs(c - BANDS[b][1]))
        return best if abs(c - BANDS[best][1]) / BANDS[best][1] < 0.3 else None

    df = df.assign(band=centre_um.apply(pick_band))

    if "t_min" in df and "t_max" in df:
        mid = (pd.to_numeric(df["t_min"], errors="coerce")
               + pd.to_numeric(df["t_max"], errors="coerce")) / 2
        df["captured_at"] = _mjd_to_ts(mid)
    else:
        df["captured_at"] = pd.NaT

    df["s_ra"] = pd.to_numeric(df["s_ra"], errors="coerce")
    df["s_dec"] = pd.to_numeric(df["s_dec"], errors="coerce")
    df = df.dropna(subset=["band", "s_ra", "s_dec", "access_url"])
    return df[["band", "access_url", "s_ra", "s_dec", "captured_at"]].reset_index(drop=True)


def build_image_rows(df: pd.DataFrame, tiles: pd.DataFrame, cutout_arcsec: float) -> list:
    """For every source and band, pick the nearest tile and build a cutout link."""
    src = SkyCoord(df["ra"].to_numpy(float) * u.deg, df["dec"].to_numpy(float) * u.deg)
    rows = []
    for band, grp in tiles.groupby("band"):
        grp = grp.reset_index(drop=True)
        tile_coords = SkyCoord(grp["s_ra"].to_numpy(float) * u.deg,
                               grp["s_dec"].to_numpy(float) * u.deg)
        idx, _, _ = src.match_to_catalog_sky(tile_coords)
        label = BANDS[band][0]
        for i, j in enumerate(idx):
            s = df.iloc[i]
            t = grp.iloc[int(j)]
            rows.append({
                "designation": s["designation"],
                "title": f"AllWISE {label.split()[0]} cutout - WISE {s['designation']}",
                "url": _cutout_url(t["access_url"], s["ra"], s["dec"], cutout_arcsec),
                "description": (f"{cutout_arcsec:g}\" x {cutout_arcsec:g}\" FITS cutout centred on "
                                f"WISE {s['designation']} from the AllWISE Atlas, band {label}."),
                "captured_at": _ts(t["captured_at"]),
            })
    return rows


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
        for b, (label, _) in BANDS.items():
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


def insert_images(cur, image_rows: list, ids: dict, source_id: int) -> int:
    cur.execute(
        "SELECT object_id, image_url FROM images "
        "WHERE source_id = %s AND object_id = ANY(%s)",
        (source_id, list(ids.values())),
    )
    existing = set(cur.fetchall())  # makes re-runs idempotent

    rows = []
    for r in image_rows:
        obj_id = ids[r["designation"]]
        if (obj_id, r["url"]) in existing:
            continue
        rows.append((obj_id, source_id, r["title"], r["url"], r["description"], r["captured_at"]))

    if not rows:
        return 0
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
def ingest(ra: float, dec: float, radius_deg: float = 0.1, row_limit: int = 100,
           with_images: bool = True, cutout_arcsec: float = DEFAULT_CUTOUT_ARCSEC) -> dict:
    df = fetch_sources(ra, dec, radius_deg, row_limit)
    if df.empty:
        print("No sources found for the given coordinates.")
        return {"sources": 0, "new_objects": 0, "observations": 0, "images": 0}

    # Image lookup is best-effort: a failure here must not block the catalog load
    image_rows = []
    if with_images:
        try:
            tiles = fetch_image_tiles(ra, dec, radius_deg)
            if tiles.empty:
                print("WARNING: no AllWISE image tiles found for this position.")
            else:
                image_rows = build_image_rows(df, tiles, cutout_arcsec)
        except Exception as exc:
            print(f"WARNING: image lookup failed ({type(exc).__name__}: {exc}); "
                  "loading catalog data only.")

    conn = connect()
    try:
        with conn.cursor() as cur:
            if STORE_MAGNITUDES:
                ensure_magnitude_columns(cur)
            source_id = get_or_create_source(cur)
            ids, n_new = upsert_objects(cur, df)
            n_obs = insert_observations(cur, df, ids, source_id)
            n_img = insert_images(cur, image_rows, ids, source_id) if image_rows else 0
        conn.commit()  # one transaction: all or nothing
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"Fetched {len(df)} sources | new celestial_objects: {n_new} | "
        f"new observations: {n_obs} | new images: {n_img}"
    )
    return {"sources": len(df), "new_objects": n_new, "observations": n_obs, "images": n_img}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Load AllWISE sources and image links into PostgreSQL.")
    p.add_argument("--ra", type=float, default=10.684, help="Right ascension [deg]")
    p.add_argument("--dec", type=float, default=41.269, help="Declination [deg]")
    p.add_argument("--radius", type=float, default=0.1, help="Cone radius [deg]")
    p.add_argument("--limit", type=int, default=100, help="Max catalog rows to fetch")
    p.add_argument("--cutout", type=float, default=DEFAULT_CUTOUT_ARCSEC,
                   help="Cutout size [arcsec]")
    p.add_argument("--no-images", action="store_true", help="Skip the images step")
    args = p.parse_args()
    ingest(args.ra, args.dec, args.radius, args.limit,
           with_images=not args.no_images, cutout_arcsec=args.cutout)