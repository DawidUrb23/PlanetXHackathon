
import re
import requests
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb
from nasa_asteroid_service import db_connection

SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
IMAGES_URL = "https://images-api.nasa.gov/search"


def clean_name(name):
    name = name.strip()

    if name.startswith("(") and name.endswith(")"):
        return name[1:-1]

    if re.match(r"^\d+\s+.+\(\d{4}\s", name):
        return name.split(" ", 1)[0]

    return name


def get_asteroid_details(name):
    lookup = clean_name(name)
    cache_key = lookup.casefold()

    # 1. Odczyt z PostgreSQL
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT response_data
                FROM asteroid_details_cache
                WHERE lookup_key = %s
                  AND expires_at > NOW()
                """,
                (cache_key,)
            )
            row = cur.fetchone()

            if row:
                print("DETAILS CACHE HIT")
                return row[0]

    print("DETAILS CACHE MISS - NASA")

    # 2. Parametry z NASA JPL
    response = requests.get(
        SBDB_URL,
        params={
            "sstr": lookup,
            "phys-par": "1"
        },
        timeout=30
    )
    response.raise_for_status()

    data = response.json()

    if "object" not in data:
        raise ValueError(
            "NASA nie zwrocila jednoznacznego obiektu"
        )

    obj = data["object"]

    # 3. Parametry fizyczne (jeżeli dostępne)
    physical = {}

    for parameter in data.get("phys_par", []):
        key = parameter.get("name")
        if key:
            physical[key] = {
                "value": parameter.get("value"),
                "units": parameter.get("units"),
                "sigma": parameter.get("sigma")
            }

    # 4. Zdjęcia NASA
    images = []

    short_name = obj.get("shortname", "")
    official_name = obj.get("fullname", lookup)

    # Szukamy zdjęć po nazwie, gdy obiekt
    # ma własną nazwę, nie tylko numer.
    candidate = re.sub(
        r"^\s*\d+\s*", "", short_name
    ).strip()

    if (
        candidate
        and re.fullmatch(r"[A-Za-z][A-Za-z-]*", candidate)
        and len(candidate) >= 4
    ):
        try:
            img_response = requests.get(
                IMAGES_URL,
                params={
                    "q": f"asteroid {candidate}",
                    "media_type": "image",
                    "page_size": 25
                },
                timeout=30
            )
            img_response.raise_for_status()

            items = img_response.json().get(
                "collection", {}
            ).get("items", [])

            for item in items:
                metadata = item.get("data", [{}])[0]
                links = item.get("links", [])

                title = metadata.get("title", "")
                description = metadata.get(
                    "description", ""
                )

                # Odrzucamy wyniki bez nazwy obiektu
                searchable = f"{title} {description}"
                if not re.search(
                    rf"\b{re.escape(candidate)}\b",
                    searchable,
                    re.IGNORECASE
                ):
                    continue

                image_url = next(
                    (
                        link.get("href")
                        for link in links
                        if link.get("render") == "image"
                        and link.get("href")
                    ),
                    None
                )

                if image_url:
                    images.append({
                        "title": title,
                        "url": image_url,
                        "description": description[:600],
                        "nasa_id": metadata.get(
                            "nasa_id"
                        ),
                        "source": "NASA Image Library"
                    })

                if len(images) >= 5:
                    break

        except requests.RequestException as exc:
            print("Nie udalo sie pobrac zdjec:", exc)

    # 5. Krótki opis oparty na danych JPL
    description = (
        f"{official_name.strip()} to obiekt "
        "Układu Słonecznego sklasyfikowany "
        "w bazie NASA JPL jako asteroida. "
    )

    if obj.get("neo") is True:
        description += (
            "Jest klasyfikowany jako obiekt "
            "bliski Ziemi (NEO). "
        )

    if "diameter" in physical:
        diameter = physical["diameter"]
        description += (
            "Podana średnica wynosi "
            f"{diameter['value']} "
            f"{diameter.get('units') or 'km'}. "
        )

    result = {
        "name": official_name.strip(),
        "identifier": obj.get("spkid"),
        "designation": obj.get("des"),
        "type": "asteroid",
        "neo": obj.get("neo"),
        "pha": obj.get("pha"),
        "description": description.strip(),
        "physical_parameters": physical,
        "images": images,
        "sources": {
            "orbital_data": SBDB_URL,
            "images": IMAGES_URL
        }
    }

    # 6. Zapis w PostgreSQL
    expires_at = datetime.now(
        timezone.utc
    ) + timedelta(hours=24)

    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asteroid_details_cache
                    (lookup_key, response_data,
                     fetched_at, expires_at)
                VALUES (%s, %s, NOW(), %s)
                ON CONFLICT (lookup_key)
                DO UPDATE SET
                    response_data = EXCLUDED.response_data,
                    fetched_at = NOW(),
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    cache_key,
                    Jsonb(result),
                    expires_at
                )
            )
        conn.commit()

    return result
