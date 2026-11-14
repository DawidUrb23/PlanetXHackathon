"""
Search the astro_test database (read-only).

Examples:
    python search_db.py J00424                     # text in name / designation / description
    python search_db.py infrared source --limit 5  # several words: all must match
    python search_db.py --id 12 15 20 --details    # by database id, with full detail
    python search_db.py --ra 10.684 --dec 41.269 --radius 0.02
    python search_db.py --band w1 --max-mag 12     # sources brighter than W1 = 12
    python search_db.py --min-bands 4 --has-images --sort brightest
    python search_db.py J0042 --csv results.csv    # export the result table
"""
import argparse
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()

BANDS = ["w1", "w2", "w3", "w4"]


def connect():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_NAME"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASS"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
    )


def like(term: str) -> str:
    """Build a safe ILIKE pattern: '%term%' with wildcards in the term escaped."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def has_magnitude_columns(cur) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = 'observations' AND column_name = 'magnitude'"
    )
    return cur.fetchone()[0] > 0


# --------------------------------------------------------------------------
# Main search query
# --------------------------------------------------------------------------
def build_query(args, with_mags: bool):
    """Inner query = one row per object with position, W1-W4 magnitudes, counts.
    Outer query = filters, sorting, limit."""
    inner_params = []

    if with_mags:
        mag_cols = ",\n".join(
            f"MAX(magnitude) FILTER (WHERE LEFT(wavelength_band, 2) = '{b.upper()}') AS {b}"
            for b in BANDS
        )
    else:
        mag_cols = ",\n".join(f"NULL::double precision AS {b}" for b in BANDS)

    cone = args.ra is not None and args.dec is not None
    if cone:
        sep = (
            "degrees(acos(least(1, greatest(-1, "
            "sin(radians(obs.dec)) * sin(radians(%s)) + "
            "cos(radians(obs.dec)) * cos(radians(%s)) * cos(radians(obs.ra - %s)))))) AS sep_deg"
        )
        inner_params += [args.dec, args.dec, args.ra]
    else:
        sep = "NULL::double precision AS sep_deg"

    inner = f"""
        WITH obs AS (
            SELECT object_id, MIN(ra) AS ra, MIN(dec) AS dec,
                   COUNT(DISTINCT wavelength_band) AS n_bands,
                   {mag_cols}
            FROM observations GROUP BY object_id
        )
        SELECT o.id, o.name, o.nasa_identifier AS designation, o.object_type, o.description,
               obs.ra, obs.dec, obs.w1, obs.w2, obs.w3, obs.w4,
               COALESCE(obs.n_bands, 0) AS n_bands,
               (SELECT COUNT(*) FROM images i WHERE i.object_id = o.id) AS n_images,
               {sep}
        FROM celestial_objects o
        LEFT JOIN obs ON obs.object_id = o.id
    """

    where, params = [], []

    if args.id:
        where.append("t.id = ANY(%s)")
        params.append(args.id)

    for term in args.text:
        where.append(
            "(t.name ILIKE %s OR t.designation ILIKE %s "
            "OR t.description ILIKE %s OR t.object_type ILIKE %s)"
        )
        params += [like(term)] * 4

    if args.type:
        where.append("t.object_type ILIKE %s")
        params.append(like(args.type))

    if cone:
        where.append("t.sep_deg <= %s")
        params.append(args.radius)

    if args.min_mag is not None:
        where.append(f"t.{args.band} >= %s")
        params.append(args.min_mag)
    if args.max_mag is not None:
        where.append(f"t.{args.band} <= %s")
        params.append(args.max_mag)

    if args.min_bands:
        where.append("t.n_bands >= %s")
        params.append(args.min_bands)

    if args.has_images:
        where.append("t.n_images > 0")

    sort = args.sort or ("separation" if cone else "id")
    order = {
        "id": "t.id",
        "name": "t.designation",
        "separation": "t.sep_deg NULLS LAST, t.id",
        "brightest": f"t.{args.band} NULLS LAST, t.id",  # smaller magnitude = brighter
    }[sort]

    sql = (
        "SELECT t.*, COUNT(*) OVER () AS total_matches FROM (" + inner + ") t "
        + (f"WHERE {' AND '.join(where)} " if where else "")
        + f"ORDER BY {order} LIMIT %s"
    )
    return sql, inner_params + params + [args.limit]


# --------------------------------------------------------------------------
# Detail view
# --------------------------------------------------------------------------
def print_details(cur, df: pd.DataFrame, with_mags: bool):
    for _, r in df.iterrows():
        print("=" * 78)
        print(f"[{r['id']}] {r['name']}   ({r['object_type']})")
        if pd.notna(r["ra"]):
            print(f"  position: RA {r['ra']:.6f}  Dec {r['dec']:.6f}")
        print(f"  {r['description']}")

        mag_cols = ", magnitude, magnitude_error" if with_mags else ""
        cur.execute(
            f"SELECT wavelength_band, data_url{mag_cols} FROM observations "
            "WHERE object_id = %s ORDER BY wavelength_band",
            (int(r["id"]),),
        )
        obs = cur.fetchall()
        print(f"  observations ({len(obs)}):")
        for row in obs:
            band, url = row[0], row[1]
            mag = ""
            if with_mags and row[2] is not None:
                err = f" +/- {row[3]:.3f}" if row[3] is not None else ""
                mag = f"  mag {row[2]:.3f}{err}"
            print(f"    {band:<14}{mag}\n      {url}")

        cur.execute(
            "SELECT title, image_url FROM images WHERE object_id = %s ORDER BY title",
            (int(r["id"]),),
        )
        imgs = cur.fetchall()
        print(f"  images ({len(imgs)}):")
        for title, url in imgs:
            print(f"    {title}\n      {url}")
    print("=" * 78)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Search the astro_test database by id, descriptor, position, band or magnitude."
    )
    p.add_argument("text", nargs="*",
                   help="words to look for in name, designation, description or type "
                        "(all words must match)")
    p.add_argument("--id", type=int, nargs="+", help="database id(s) of celestial_objects")
    p.add_argument("--type", help="object type contains this text, e.g. 'infrared'")

    p.add_argument("--ra", type=float, help="cone search centre RA [deg] (needs --dec)")
    p.add_argument("--dec", type=float, help="cone search centre Dec [deg] (needs --ra)")
    p.add_argument("--radius", type=float, default=0.1, help="cone radius [deg] (default 0.1)")

    p.add_argument("--band", choices=BANDS, default="w1",
                   help="band used by --min-mag / --max-mag / --sort brightest (default w1)")
    p.add_argument("--min-mag", type=float, help="magnitude in --band at least this value (fainter)")
    p.add_argument("--max-mag", type=float, help="magnitude in --band at most this value (brighter)")
    p.add_argument("--min-bands", type=int, choices=[1, 2, 3, 4],
                   help="detected in at least N bands")
    p.add_argument("--has-images", action="store_true", help="only sources with stored image links")

    p.add_argument("--sort", choices=["id", "name", "separation", "brightest"],
                   help="default: separation for cone searches, otherwise id")
    p.add_argument("--limit", type=int, default=20, help="max rows to show (default 20)")
    p.add_argument("--details", action="store_true",
                   help="print observations and image URLs for each result")
    p.add_argument("--csv", metavar="FILE", help="also save the result table to a CSV file")
    args = p.parse_args()

    if (args.ra is None) != (args.dec is None):
        p.error("--ra and --dec must be given together")

    conn = connect()
    try:
        with conn.cursor() as cur:
            with_mags = has_magnitude_columns(cur)
            wants_mags = (args.min_mag is not None or args.max_mag is not None
                          or args.sort == "brightest")
            if wants_mags and not with_mags:
                p.error("the observations table has no magnitude column "
                        "(it is created by ETL_bridge.py when STORE_MAGNITUDES = True)")

            sql, params = build_query(args, with_mags)
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()

            if not rows:
                print("No matches.")
                return

            df = pd.DataFrame(rows, columns=columns)
            total = int(df["total_matches"].iloc[0])
            df = df.drop(columns=["total_matches"])

            table = df.drop(columns=["description"]).rename(columns={"n_bands": "bands", "n_images": "imgs"})
            if args.ra is None:
                table = table.drop(columns=["sep_deg"])
            if not with_mags:
                table = table.drop(columns=BANDS)
            for col in ["ra", "dec"]:
                table[col] = pd.to_numeric(table[col]).round(5)
            for col in BANDS + ["sep_deg"]:
                if col in table:
                    table[col] = pd.to_numeric(table[col]).round(3)
            for col in BANDS:
                if col in table and table[col].isna().all():
                    table = table.drop(columns=col)
            print(table.to_string(index=False, na_rep="-"))
            print(f"\nShowing {len(df)} of {total} matching source(s).")

            if args.csv:
                table.to_csv(args.csv, index=False)
                print(f"Saved {args.csv}")

            if args.details:
                print()
                print_details(cur, df, with_mags)
    finally:
        conn.close()


if __name__ == "__main__":
    main()