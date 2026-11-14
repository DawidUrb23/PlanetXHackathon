"""
Download selected AllWISE cutouts (links stored in the `images` table) to disk.

Selection (pick one; default is --limit 5 as a safety net):
    python download_images.py J004244.37+411609.0 J004245.10+411550.2   # named sources
    python download_images.py --brightest 10                            # 10 brightest in W1
    python download_images.py --limit 20                                # first 20 sources
    python download_images.py --all                                     # everything

Filters / options:
    --bands w1 w2        only these bands (default: all four)
    --out images         output folder (default: ./images)
    --png                also render a viewable PNG next to each FITS file
"""
import argparse
import os
import requests

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def connect():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_NAME"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASS"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
    )


def select_images(args):
    where = ["o.object_type = 'infrared source'"]
    params = []

    if args.designations:
        where.append("o.nasa_identifier = ANY(%s)")
        params.append(args.designations)
    elif args.brightest:
        # smaller magnitude = brighter; uses the W1 magnitude stored in observations
        where.append(
            "o.id IN (SELECT object_id FROM observations "
            "WHERE wavelength_band LIKE 'W1%%' AND magnitude IS NOT NULL "
            "ORDER BY magnitude ASC LIMIT %s)"
        )
        params.append(args.brightest)
    elif not args.all:
        where.append(
            "o.id IN (SELECT id FROM celestial_objects "
            "WHERE object_type = 'infrared source' ORDER BY id LIMIT %s)"
        )
        params.append(args.limit)

    if args.bands:
        where.append("i.title LIKE ANY(%s)")
        params.append([f"AllWISE {b.upper()} %" for b in args.bands])

    sql = (
        "SELECT o.nasa_identifier, i.title, i.image_url "
        "FROM images i JOIN celestial_objects o ON o.id = i.object_id "
        f"WHERE {' AND '.join(where)} ORDER BY o.id, i.title"
    )
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def render_png(fits_path: str, png_path: str, title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from astropy.io import fits
    from astropy.visualization import AsinhStretch, ImageNormalize, ZScaleInterval

    with fits.open(fits_path) as hdul:
        hdu = next(h for h in hdul if h.data is not None)
        data = hdu.data.astype(float)

    fig, ax = plt.subplots(figsize=(5, 5))
    norm = ImageNormalize(data, interval=ZScaleInterval(), stretch=AsinhStretch())
    ax.imshow(data, origin="lower", cmap="inferno", norm=norm)
    ax.set_title(title, fontsize=9)
    ax.axis("off")
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description="Download selected AllWISE cutouts.")
    p.add_argument("designations", nargs="*", help="WISE designations, e.g. J004244.37+411609.0")
    p.add_argument("--brightest", type=int, help="the N brightest sources in W1")
    p.add_argument("--limit", type=int, default=5, help="first N sources (default 5)")
    p.add_argument("--all", action="store_true", help="download every stored image")
    p.add_argument("--bands", nargs="+", choices=["w1", "w2", "w3", "w4"], help="bands to keep")
    p.add_argument("--out", default="images", help="output folder")
    p.add_argument("--png", action="store_true", help="also write a PNG preview")
    args = p.parse_args()

    rows = select_images(args)
    if not rows:
        print("No images matched the selection.")
        return

    os.makedirs(args.out, exist_ok=True)
    ok = skipped = failed = 0
    for designation, title, url in rows:
        band = title.split()[1]  # "AllWISE W1 cutout - ..." -> "W1"
        base = f"{designation}_{band}"
        fits_path = os.path.join(args.out, base + ".fits")

        if os.path.exists(fits_path):
            skipped += 1
        else:
            try:
                resp = requests.get(url, timeout=120)
                resp.raise_for_status()
                with open(fits_path, "wb") as f:
                    f.write(resp.content)
                ok += 1
                print(f"saved {fits_path}")
            except Exception as exc:
                failed += 1
                print(f"FAILED {base}: {type(exc).__name__}: {exc}")
                continue

        if args.png:
            try:
                render_png(fits_path, os.path.join(args.out, base + ".png"), f"{designation} {band}")
            except Exception as exc:
                print(f"PNG failed for {base}: {type(exc).__name__}: {exc}")

    print(f"Done: {ok} downloaded, {skipped} already present, {failed} failed -> {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()