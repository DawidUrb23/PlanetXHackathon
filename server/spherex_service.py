
import json
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl
import time
from psycopg.types.json import Jsonb

from nasa_asteroid_service import db_connection
from ETL_bridge import fetch_spectral_images


CACHE_HOURS = 24


def make_cutout_url(file_url, ra, dec, size_deg=0.02):
    """Adres wycinka FITS z archiwum IRSA."""
    parts = urlsplit(file_url)

    # Tworzymy URL tylko dla obsługiwanych adresów IRSA.
    if parts.scheme != "https" or parts.hostname != "irsa.ipac.caltech.edu":
        return None

    query = dict(parse_qsl(parts.query))
    query["center"] = f"{ra},{dec}"
    query["size"] = str(size_deg)

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        ""
    ))


def get_spherex_observations(
    ra,
    dec,
    limit=50,
    bands=None
):
    """Zwraca obserwacje SPHEREx lub zapisany wynik."""

    if not 0 <= ra < 360:
        raise ValueError("RA musi byc w zakresie 0-360")

    if not -90 <= dec <= 90:
        raise ValueError("Dec musi byc w zakresie -90 do 90")

    if not 1 <= limit <= 50:
        raise ValueError("Limit musi byc od 1 do 50")

    bands = sorted(set(bands or []))

    if any(b not in range(1, 7) for b in bands):
        raise ValueError("Dozwolone pasma: 1-6")

    params = {
        "ra": round(ra, 6),
        "dec": round(dec, 6),
        "limit": limit,
        "bands": bands
    }

    canonical = json.dumps(
        params,
        sort_keys=True,
        separators=(",", ":")
    )

    query_hash = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    # 1. Sprawdzamy PostgreSQL
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT response_data
                FROM spherex_cache
                WHERE query_hash = %s
                  AND expires_at > NOW()
                """,
                (query_hash,)
            )

            row = cur.fetchone()

            if row:
                print("SPHEREX CACHE HIT")
                return {
                    "source": "cache",
                    "data": row[0]
                }

    print("SPHEREX CACHE MISS - pobieram dane z IRSA")

    # 2. Pobieranie metadanych obserwacji NASA
    print("Rozpoczynam wyszukiwanie obserwacji SPHEREx...")

    start_time = time.perf_counter()

    df = fetch_spectral_images(
        ra=ra,
        dec=dec,
        limit=limit,
        bands=bands or None,
        all_versions=False
    )

    elapsed = time.perf_counter() - start_time

    print(f"Czas zapytania NASA IRSA: {elapsed:.2f} sekund")
    print(f"Liczba pobranych obserwacji: {len(df)}")

    observations = []

    for _, record in df.iterrows():

        observed_at = record.get("observed_at")

        if observed_at is not None:
            import pandas as pd
            if pd.isna(observed_at):
                observed_at = None
            else:
                observed_at = observed_at.isoformat()

        file_url = str(record["file_url"])

        observations.append({
            "observed_at": observed_at,
            "band": str(record["band_label"]),
            "version": str(record["version"]),
            "data_url": file_url,
            "cutout_url": make_cutout_url(
                file_url, ra, dec
            ),
            "format": "FITS"
        })

    result = {
        "target": {
            "ra": ra,
            "dec": dec,
            "coordinate_system": "ICRS"
        },
        "count": len(observations),
        "observations": observations,
        "archive": "NASA/IPAC IRSA SPHEREx"
    }

    # 3. Zapisujemy do PostgreSQL
    expires_at = datetime.now(
        timezone.utc
    ) + timedelta(hours=CACHE_HOURS)

    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO spherex_cache (
                    query_hash,
                    query_params,
                    response_data,
                    fetched_at,
                    expires_at
                )
                VALUES (%s, %s, %s, NOW(), %s)
                ON CONFLICT (query_hash)
                DO UPDATE SET
                    query_params = EXCLUDED.query_params,
                    response_data = EXCLUDED.response_data,
                    fetched_at = NOW(),
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    query_hash,
                    Jsonb(params),
                    Jsonb(result),
                    expires_at
                )
            )

        conn.commit()

    print("Zapisano wynik SPHEREx w PostgreSQL")

    return {
        "source": "irsa",
        "data": result
    }


if __name__ == "__main__":
    result = get_spherex_observations(
        ra=10.684,
        dec=41.269,
        limit=50
    )

    print("Zrodlo:", result["source"])
    print("Liczba obserwacji:", result["data"]["count"])

    for obs in result["data"]["observations"][:3]:
        print(json.dumps(
            obs, indent=2, ensure_ascii=False
        ))
