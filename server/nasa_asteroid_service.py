
import os
import json
import hashlib
from datetime import datetime, timedelta, timezone

import requests
import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()

NASA_URL = "https://ssd-api.jpl.nasa.gov/sb_ident.api"
CACHE_MINUTES = 10


def db_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "nasa_spaceapps"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD")
    )


def get_asteroids(
    latitude,
    longitude,
    altitude_km,
    observation_time,
    ra_center,
    dec_center,
    ra_half_width=1.0,
    dec_half_width=1.0,
    magnitude_limit=20.0
):
    """
    observation_time: datetime z UTC
    ra_center: np. "03-00-00"
    dec_center: np. "20-00-00"
    """

    if observation_time.tzinfo is None:
        raise ValueError("Czas musi zawierac strefe UTC")

    utc_time = observation_time.astimezone(timezone.utc)

    # Wszystkie parametry, które mają wpływ na wynik
    params = {
        "lat": latitude,
        "lon": longitude,
        "alt": altitude_km,
        "obs-time": utc_time.strftime(
            "%Y-%m-%d_%H:%M:%S"
        ),
        "fov-ra-center": ra_center,
        "fov-dec-center": dec_center,
        "fov-ra-hwidth": ra_half_width,
        "fov-dec-hwidth": dec_half_width,
        "vmag-lim": magnitude_limit,
        "mag-required": "true",
        "sb-kind": "a",
        "two-pass": "true",
        "suppress-first-pass": "true",
        "req-elem": "false"
    }

    # Stabilny identyfikator zapytania
    canonical = json.dumps(
        params, sort_keys=True, separators=(",", ":")
    )
    query_hash = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    with db_connection() as conn:
        with conn.cursor() as cur:

            # 1. Sprawdzenie istniejącego cache
            cur.execute(
                """
                SELECT response_data
                FROM asteroid_cache
                WHERE query_hash = %s
                  AND expires_at > NOW()
                """,
                (query_hash,)
            )

            cached = cur.fetchone()

            if cached:
                print("CACHE HIT - dane z PostgreSQL")

                return {
                    "source": "cache",
                    "data": cached[0]
                }

    print("CACHE MISS - pobieram dane z NASA")

    # 2. Pobranie danych z NASA
    response = requests.get(
        NASA_URL,
        params=params,
        timeout=90
    )
    response.raise_for_status()

    nasa_data = response.json()

    if "error" in nasa_data:
        raise RuntimeError(nasa_data["error"])

    version = nasa_data.get(
        "signature", {}
    ).get("version")

    if version != "1.1":
        raise RuntimeError(
            f"Nieznana wersja API NASA: {version}"
        )

    if "fields_second" not in nasa_data:
        raise RuntimeError(
            "Brak oczekiwanych pol w odpowiedzi NASA"
        )

    fields = nasa_data["fields_second"]
    rows = nasa_data.get("data_second_pass", [])

    objects = []

    for row in rows:
        asteroid = dict(zip(fields, row))

        def number(field):
            value = asteroid.get(field)
            if value in (None, "", "n.a.", "N/A"):
                return None
            return float(value)

        objects.append({
            "name": asteroid["Object name"],
            "ra": asteroid[
                "Astrometric RA (hh:mm:ss)"
            ],
            "dec": asteroid[
                "Astrometric Dec (dd mm'ss\")"
            ],
            "magnitude": number(
                "Visual magnitude (V)"
            ),
            "distance_from_center_deg": (
                number(
                    'Dist. from center Norm (")'
                ) / 3600.0
            )
        })

    result = {
        "observation_time": params["obs-time"],
        "observer": {
            "latitude": latitude,
            "longitude": longitude,
            "altitude_km": altitude_km
        },
        "field_of_view": {
            "ra_center": ra_center,
            "dec_center": dec_center,
            "ra_half_width": ra_half_width,
            "dec_half_width": dec_half_width
        },
        "count": len(objects),
        "objects": objects
    }

    # 3. Zapis wyniku w PostgreSQL
    expires_at = datetime.now(
        timezone.utc
    ) + timedelta(minutes=CACHE_MINUTES)

    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asteroid_cache
                    (
                        query_hash,
                        query_params,
                        response_data,
                        nasa_source,
                        fetched_at,
                        expires_at
                    )
                VALUES (%s, %s, %s, %s, NOW(), %s)
                ON CONFLICT (query_hash)
                DO UPDATE SET
                    query_params = EXCLUDED.query_params,
                    response_data = EXCLUDED.response_data,
                    nasa_source = EXCLUDED.nasa_source,
                    fetched_at = NOW(),
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    query_hash,
                    Jsonb(params),
                    Jsonb(result),
                    NASA_URL,
                    expires_at
                )
            )

        conn.commit()

    print("Zapisano wynik w PostgreSQL")

    return {
        "source": "nasa",
        "data": result
    }


if __name__ == "__main__":

    # Stała data testowa, aby sprawdzić cache.
    # Przy integracji podamy aktualny czas z aplikacji.
    test_time = datetime(
        2026, 11, 14, 20, 0, 0,
        tzinfo=timezone.utc
    )

    result = get_asteroids(
        latitude=50.3,
        longitude=18.8,
        altitude_km=0.3,
        observation_time=test_time,
        ra_center="03-00-00",
        dec_center="20-00-00",
        ra_half_width=1.0,
        dec_half_width=1.0,
        magnitude_limit=20.0
    )

    print("Zrodlo:", result["source"])
    print("Liczba asteroid:", result["data"]["count"])

    for obj in result["data"]["objects"][:10]:
        print(obj)
