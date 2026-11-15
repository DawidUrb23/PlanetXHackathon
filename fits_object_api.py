
import hmac
import os
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query
from psycopg.rows import dict_row

from nasa_asteroid_service import db_connection

router = APIRouter(
    prefix="/api/fits/objects",
    tags=["FITS by object"]
)


# 1. Znajdowanie obiektu w PostgreSQL
def find_object(name: str):
    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:

            # Najpierw katalog 100 znanych obiektow
            cur.execute("""
                SELECT to_regclass(
                    'public.featured_sky_objects'
                ) AS table_name
            """)

            if cur.fetchone()["table_name"] is not None:
                cur.execute("""
                    SELECT object_key, name, designation,
                           is_moving, ra_deg, dec_deg
                    FROM featured_sky_objects
                    WHERE name ILIKE %s
                       OR designation ILIKE %s
                       OR object_key ILIKE %s
                    LIMIT 1
                """, (name, name, name))

                obj = cur.fetchone()

                if obj:
                    if obj["is_moving"]:
                        raise HTTPException(
                            status_code=422,
                            detail="Obiekt ruchomy wymaga "
                                   "historycznych efemeryd"
                        )

                    if obj["ra_deg"] is None or obj["dec_deg"] is None:
                        raise HTTPException(
                            status_code=422,
                            detail="Obiekt nie ma wspolrzednych RA/Dec"
                        )

                    return {
                        "ref": "featured:" + str(obj["object_key"]),
                        "name": obj["name"],
                        "ra": float(obj["ra_deg"]),
                        "dec": float(obj["dec_deg"])
                    }

            # Jesli nie znaleziono, szukamy w glownym katalogu
            cur.execute("""
                SELECT o.id, o.name, o.object_type,
                       obs.ra, obs.dec
                FROM celestial_objects o
                LEFT JOIN LATERAL (
                    SELECT ra, dec
                    FROM observations
                    WHERE object_id = o.id
                      AND ra IS NOT NULL
                      AND dec IS NOT NULL
                    ORDER BY observed_at DESC NULLS LAST,
                             id DESC
                    LIMIT 1
                ) obs ON TRUE
                WHERE o.name ILIKE %s
                   OR o.nasa_identifier ILIKE %s
                LIMIT 1
            """, (name, name))

            obj = cur.fetchone()

            if obj is None:
                raise HTTPException(
                    status_code=404,
                    detail="Nie znaleziono obiektu w PostgreSQL"
                )

            if obj["object_type"] in (
                "planet", "asteroid", "comet",
                "dwarf_planet", "satellite"
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Obiekt ruchomy wymaga "
                           "historycznych efemeryd"
                )

            if obj["ra"] is None or obj["dec"] is None:
                raise HTTPException(
                    status_code=422,
                    detail="Brak wspolrzednych RA/Dec"
                )

            return {
                "ref": "celestial:" + str(obj["id"]),
                "name": obj["name"],
                "ra": float(obj["ra"]),
                "dec": float(obj["dec"])
            }


# 2. Odczytywanie przypisanych plikow FITS
def get_object_files(object_ref: str):
    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    a.id,
                    a.remote_url,
                    a.collection,
                    a.title,
                    a.mime_type,
                    a.size_bytes,
                    a.status,
                    a.downloaded_at,
                    l.observed_at,
                    l.wavelength_band,
                    l.match_method
                FROM fits_object_links l
                JOIN fits_assets a
                    ON a.id = l.fits_asset_id
                WHERE l.object_ref = %s
                ORDER BY l.observed_at DESC NULLS LAST,
                         a.id DESC
            """, (object_ref,))

            records = cur.fetchall()

    return [
        {
            key: value.isoformat()
            if isinstance(value, datetime) else value
            for key, value in record.items()
        }
        for record in records
    ]


# 3. Endpoint dla telefonu - tylko PostgreSQL
@router.get("")
def list_object_fits(
    name: str = Query(..., min_length=1, max_length=160)
):
    obj = find_object(name.strip())
    files = get_object_files(obj["ref"])

    return {
        "object": obj,
        "count": len(files),
        "files": files,
        "source": "postgresql"
    }


# 4. Indeksowanie obserwacji z NASA SPHEREx
@router.post("/index")
def index_object_fits(
    name: str = Query(..., min_length=1, max_length=160),
    limit: int = Query(5, ge=1, le=20),
    x_admin_key: str | None = Header(default=None)
):
    # Ochrona kosztownej operacji indeksowania
    secret = os.getenv("FITS_ADMIN_KEY", "")

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Brak FITS_ADMIN_KEY w .env"
        )

    if not x_admin_key or not hmac.compare_digest(
        x_admin_key, secret
    ):
        raise HTTPException(
            status_code=403,
            detail="Brak uprawnien"
        )

    obj = find_object(name.strip())

    # EXTRACT - funkcja ETL kolegi
    try:
        from etl_spherex import fetch_spectral_images

        df = fetch_spectral_images(
            ra=obj["ra"],
            dec=obj["dec"],
            limit=limit,
            bands=None,
            all_versions=False
        )

    except Exception as exc:
        print("SPHEREX ETL ERROR:", repr(exc))
        raise HTTPException(
            status_code=502,
            detail="Nie udalo sie wyszukac obserwacji SPHEREx"
        )

    indexed = 0

    # LOAD - zapis metadanych FITS do PostgreSQL
    with db_connection() as conn:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                url = str(row.get("file_url") or "").strip()
                parsed = urlparse(url)

                # Rejestrujemy tylko bezposrednie adresy HTTPS
                if parsed.scheme != "https" or not parsed.hostname:
                    continue

                band = str(
                    row.get("band_label")
                    or row.get("bandpass")
                    or "SPHEREx"
                )

                observed_at = row.get("observed_at")

                if hasattr(observed_at, "to_pydatetime"):
                    observed_at = observed_at.to_pydatetime()

                if not isinstance(observed_at, datetime):
                    observed_at = None

                # Jeden unikatowy rekord dla kazdego adresu FITS
                cur.execute("""
                    INSERT INTO fits_assets
                        (remote_url, collection,
                         ra_center, dec_center,
                         title, mime_type)
                    VALUES
                        (%s, 'spherex_etl', %s, %s,
                         %s, 'application/fits')
                    ON CONFLICT (remote_url)
                    DO UPDATE SET title = EXCLUDED.title
                    RETURNING id
                """, (
                    url,
                    obj["ra"],
                    obj["dec"],
                    obj["name"] + " - " + band
                ))

                fits_id = cur.fetchone()[0]

                # Powiazanie FITS z konkretnym obiektem
                cur.execute("""
                    INSERT INTO fits_object_links
                        (fits_asset_id, object_ref,
                         object_name, target_ra, target_dec,
                         observed_at, wavelength_band)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (fits_asset_id, object_ref)
                    DO UPDATE SET
                        observed_at = EXCLUDED.observed_at,
                        wavelength_band = EXCLUDED.wavelength_band
                """, (
                    fits_id,
                    obj["ref"],
                    obj["name"],
                    obj["ra"],
                    obj["dec"],
                    observed_at,
                    band
                ))

                indexed += 1

        conn.commit()

    files = get_object_files(obj["ref"])

    return {
        "object": obj,
        "indexed_this_request": indexed,
        "count": len(files),
        "files": files
    }
